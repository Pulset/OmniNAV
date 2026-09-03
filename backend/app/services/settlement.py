"""每日清算编排：加载流水/行情 → 估值 → NAV 核算 → 快照 upsert。

调用方：
- 06:00 终局清算 / 22:00 预估简报：先 detect_replay_start 修复历史链，
  再 run_settlement 当日（persist=True / False）。
- 历史回放回补与流水变更触发的自动修复：replay_settlements 逐日 persist，
  单事务提交（中途失败整体回滚，dirty 标记保留待重试）。
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DimAsset,
    FactDailyMarketData,
    FactManualNav,
    FactPortfolioSnapshot,
    FactTransaction,
    SysSettlementState,
)
from app.services.nav import Q2, Q4, ZERO, NavResult, settle_day
from app.services.portfolio import (
    aggregate_diluted_cost,
    aggregate_holdings,
    net_cash_flow_cny,
)
from app.services.valuation import (
    AssetLike,
    PositionValuation,
    PriceBook,
    manual_nav_symbol,
    value_asset,
)

logger = logging.getLogger(__name__)

CSI300_SYMBOL = "CSI300"
SP500_SYMBOL = "SP500"
NASDAQ_SYMBOL = "NASDAQ"

# 每日链基：(unit_nav, total_shares, total_market_value_cny)
PrevValues = tuple[Decimal, Decimal, Decimal]


@dataclass
class SettlementResult:
    target_date: date
    nav: NavResult
    valuations: list[PositionValuation]  # 当日终局持仓估值
    valuations_before_flow: list[PositionValuation]  # 昨日持仓按今日价格估值
    net_flow_cny: Decimal
    mv_end_of_day: Decimal
    mv_before_flow: Decimal
    csi300_nav: Decimal | None
    sp500_nav: Decimal | None
    nasdaq_nav: Decimal | None
    persisted: bool


@dataclass
class SettlementContext:
    """单用户清算所需的全部输入，回放时加载一次逐日复用。"""

    assets: dict[str, AssetLike]
    book: PriceBook  # 公共行情 + 该用户 MANUAL_NAV 净值（命名空间隔离）
    txns: list[FactTransaction]  # 不晚于 up_to 的全量流水（按日期、id 升序）


def _to_asset_like(a: DimAsset) -> AssetLike:
    return AssetLike(
        asset_id=a.asset_id,
        name=a.name,
        asset_class=a.asset_class,
        market=a.market,
        currency=a.currency,
        valuation_type=a.valuation_type,
        expected_apr=Decimal(a.expected_apr),
    )


async def _load_price_book(
    session: AsyncSession, up_to: date, *, user_id: int | None = None
) -> PriceBook:
    """全局行情簿；user_id 给出时并入该用户的 MANUAL_NAV 净值。"""
    market_rows = (
        await session.execute(
            select(
                FactDailyMarketData.trade_date,
                FactDailyMarketData.symbol,
                FactDailyMarketData.close_price,
            ).where(FactDailyMarketData.trade_date <= up_to)
        )
    ).all()
    if user_id is None:
        return PriceBook(market_rows)
    manual_rows = (
        await session.execute(
            select(
                FactManualNav.nav_date,
                FactManualNav.asset_id,
                FactManualNav.nav,
            ).where(
                FactManualNav.user_id == user_id,
                FactManualNav.nav_date <= up_to,
            )
        )
    ).all()
    return PriceBook(
        list(market_rows)
        + [(d, manual_nav_symbol(aid), nav) for d, aid, nav in manual_rows]
    )


async def _load_context(
    session: AsyncSession, user_id: int, up_to: date
) -> SettlementContext:
    txns = (
        (
            await session.execute(
                select(FactTransaction)
                .where(
                    FactTransaction.user_id == user_id,
                    FactTransaction.trans_date <= up_to,
                )
                .order_by(FactTransaction.trans_date, FactTransaction.id)
            )
        )
        .scalars()
        .all()
    )
    assets = {
        a.asset_id: _to_asset_like(a)
        for a in (
            await session.execute(
                select(DimAsset).where(DimAsset.user_id == user_id)
            )
        ).scalars()
    }
    book = await _load_price_book(session, up_to, user_id=user_id)
    return SettlementContext(assets=assets, book=book, txns=list(txns))


async def get_latest_snapshot(
    session: AsyncSession, user_id: int, before: date
) -> FactPortfolioSnapshot | None:
    return (
        await session.execute(
            select(FactPortfolioSnapshot)
            .where(
                FactPortfolioSnapshot.user_id == user_id,
                FactPortfolioSnapshot.snapshot_date < before,
            )
            .order_by(FactPortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_first_snapshot_date(session: AsyncSession, user_id: int) -> date | None:
    d = (
        await session.execute(
            select(FactPortfolioSnapshot.snapshot_date)
            .where(FactPortfolioSnapshot.user_id == user_id)
            .order_by(FactPortfolioSnapshot.snapshot_date.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return d


async def _prev_values(
    session: AsyncSession, user_id: int, before: date
) -> PrevValues | None:
    prev = await get_latest_snapshot(session, user_id, before)
    if prev is None:
        return None
    return (
        Decimal(prev.unit_nav),
        Decimal(prev.total_shares),
        Decimal(prev.total_market_value_cny),
    )


def _normalized_benchmark(
    book: PriceBook, symbol: str, base_date: date, target: date
) -> Decimal | None:
    base = book.close(symbol, base_date)
    cur = book.close(symbol, target)
    if not base or base == ZERO or not cur:
        return None
    return (cur / base).quantize(Q4, ROUND_HALF_UP)


def _settle_day_from_ctx(
    ctx: SettlementContext,
    target_date: date,
    prev: PrevValues | None,
    base_date: date,
) -> tuple[SettlementResult, PrevValues]:
    """纯计算：单日清算（不落库），返回 (结果, 新链基)。"""
    txns = ctx.txns
    holdings_today = aggregate_holdings([t for t in txns if t.trans_date <= target_date])
    holdings_before = aggregate_holdings(
        [t for t in txns if t.trans_date < target_date]
    )
    diluted = aggregate_diluted_cost(
        [t for t in txns if t.trans_date <= target_date]
    )

    def _value_all(holdings: dict[str, list]) -> list[PositionValuation]:
        return [
            value_asset(
                ctx.assets[aid],
                lots,
                ctx.book,
                target_date,
                diluted_cost=diluted.get(aid),
            )
            for aid, lots in holdings.items()
            if aid in ctx.assets
        ]

    valuations = _value_all(holdings_today)
    valuations_before_flow = _value_all(holdings_before)

    mv_today = sum((v.market_value_cny for v in valuations), ZERO)
    mv_before_flow = sum((v.market_value_cny for v in valuations_before_flow), ZERO)

    flow = net_cash_flow_cny(
        [t for t in txns if t.trans_date == target_date],
        lambda cur, d: ctx.book.fx_to_cny(cur, d),
    )

    yesterday_nav, yesterday_shares, yesterday_mv = prev or (ZERO, ZERO, ZERO)
    nav = settle_day(
        yesterday_nav=yesterday_nav,
        yesterday_shares=yesterday_shares,
        yesterday_total_mv=yesterday_mv,
        today_mv_before_flow=mv_before_flow,
        today_mv_end_of_day=mv_today,
        today_net_cash_flow=flow,
    )

    # 基准指数归一化：以该用户组合首个快照日（无则回放首日）为 1.0000 基点
    csi300_nav = _normalized_benchmark(ctx.book, CSI300_SYMBOL, base_date, target_date)
    sp500_nav = _normalized_benchmark(ctx.book, SP500_SYMBOL, base_date, target_date)
    nasdaq_nav = _normalized_benchmark(
        ctx.book, NASDAQ_SYMBOL, base_date, target_date
    )

    result = SettlementResult(
        target_date=target_date,
        nav=nav,
        valuations=valuations,
        valuations_before_flow=valuations_before_flow,
        net_flow_cny=flow,
        mv_end_of_day=mv_today,
        mv_before_flow=mv_before_flow,
        csi300_nav=csi300_nav,
        sp500_nav=sp500_nav,
        nasdaq_nav=nasdaq_nav,
        persisted=False,
    )
    return result, (nav.unit_nav, nav.total_shares, mv_today)


async def run_settlement(
    session: AsyncSession, target_date: date, *, user_id: int, persist: bool = True
) -> SettlementResult | None:
    """对 target_date 执行某用户的 NAV 清算。该用户无任何流水时返回 None。"""
    ctx = await _load_context(session, user_id, target_date)
    if not ctx.txns:
        return None

    prev = await _prev_values(session, user_id, target_date)
    base_date = (await get_first_snapshot_date(session, user_id)) or target_date
    result, _ = _settle_day_from_ctx(ctx, target_date, prev, base_date)

    if persist:
        await _upsert_snapshot(
            session,
            user_id,
            target_date,
            mv_today=result.mv_end_of_day,
            nav=result.nav,
            csi300_nav=result.csi300_nav,
            sp500_nav=result.sp500_nav,
            nasdaq_nav=result.nasdaq_nav,
        )
        await session.commit()
        result.persisted = True
    return result


async def replay_settlements(
    session: AsyncSession, user_id: int, start: date, end: date
) -> SettlementResult | None:
    """从 start 到 end 逐日重放清算并 upsert，单事务提交。

    上下文（流水/资产/行情簿）只加载一次，链基在内存中逐日推进；
    重复跑批覆盖更新但保留已录入的复盘日记。返回最后一日结果，
    无流水返回 None。调用方负责 commit 失败时保留 dirty 标记。
    """
    ctx = await _load_context(session, user_id, end)
    if not ctx.txns:
        return None

    prev = await _prev_values(session, user_id, start)
    base_date = (await get_first_snapshot_date(session, user_id)) or start
    result: SettlementResult | None = None
    d = start
    while d <= end:
        result, prev = _settle_day_from_ctx(ctx, d, prev, base_date)
        await _upsert_snapshot(
            session,
            user_id,
            d,
            mv_today=result.mv_end_of_day,
            nav=result.nav,
            csi300_nav=result.csi300_nav,
            sp500_nav=result.sp500_nav,
            nasdaq_nav=result.nasdaq_nav,
        )
        d += timedelta(days=1)
    await session.commit()
    if result is not None:
        result.persisted = True
    return result


async def mark_settlement_dirty(
    session: AsyncSession, user_id: int, affected_from: date
) -> None:
    """流水新增/修改/删除后，标记清算链从 affected_from 起失效。

    仅当存在不早于该日的快照时才需要（更早的变更不影响既有链）；
    重复标记原子取更早日期。
    """
    latest = (
        await session.execute(
            select(func.max(FactPortfolioSnapshot.snapshot_date)).where(
                FactPortfolioSnapshot.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if latest is None or latest < affected_from:
        return
    stmt = pg_insert(SysSettlementState).values(
        user_id=user_id, dirty_from=affected_from
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "dirty_from": func.least(
                SysSettlementState.dirty_from, stmt.excluded.dirty_from
            )
        },
    )
    await session.execute(stmt)


async def detect_replay_start(
    session: AsyncSession, user_id: int, up_to: date
) -> date | None:
    """返回需要回放的最早日期（含该日）；无需回放返回 None。

    两种来源：
    - 显式 dirty 标记（流水变更后 mark_settlement_dirty 写入）
    - 链头缺失：首笔交易早于首快照（导入历史后从未回放，冷启动防护）
    """
    first_txn = (
        await session.execute(
            select(func.min(FactTransaction.trans_date)).where(
                FactTransaction.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if first_txn is None:
        return None

    candidates: list[date] = []
    state = await session.get(SysSettlementState, user_id)
    if state is not None and state.dirty_from <= up_to:
        candidates.append(state.dirty_from)
    first_snap = await get_first_snapshot_date(session, user_id)
    if first_snap is None or first_snap > first_txn:
        candidates.append(first_txn)
    if not candidates:
        return None
    return max(min(candidates), first_txn)


async def clear_settlement_dirty(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        delete(SysSettlementState).where(SysSettlementState.user_id == user_id)
    )


async def ensure_chain_current(
    session: AsyncSession, user_id: int, up_to_exclusive: date
) -> None:
    """把历史清算链修复到 up_to_exclusive 前一天（不含当日，当日留给预估/终局）。

    22:00 简报与月报在读取快照前调用；回放失败抛出，dirty 标记保留待重试。
    """
    replay_from = await detect_replay_start(session, user_id, up_to_exclusive)
    if replay_from is None or replay_from >= up_to_exclusive:
        return
    await replay_settlements(
        session, user_id, replay_from, up_to_exclusive - timedelta(days=1)
    )
    await clear_settlement_dirty(session, user_id)
    await session.commit()


async def _upsert_snapshot(
    session: AsyncSession,
    user_id: int,
    target_date: date,
    *,
    mv_today: Decimal,
    nav: NavResult,
    csi300_nav: Decimal | None,
    sp500_nav: Decimal | None,
    nasdaq_nav: Decimal | None,
) -> None:
    """幂等写入快照；重复跑批覆盖更新，但保留已录入的复盘日记。"""
    stmt = pg_insert(FactPortfolioSnapshot).values(
        user_id=user_id,
        snapshot_date=target_date,
        total_market_value_cny=mv_today.quantize(Q2),
        unit_nav=nav.unit_nav,
        total_shares=nav.total_shares,
        daily_pnl_cny=nav.daily_pnl_cny,
        daily_return=nav.daily_return,
        csi300_nav=csi300_nav,
        sp500_nav=sp500_nav,
        nasdaq_nav=nasdaq_nav,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "snapshot_date"],
        set_={
            "total_market_value_cny": stmt.excluded.total_market_value_cny,
            "unit_nav": stmt.excluded.unit_nav,
            "total_shares": stmt.excluded.total_shares,
            "daily_pnl_cny": stmt.excluded.daily_pnl_cny,
            "daily_return": stmt.excluded.daily_return,
            "csi300_nav": stmt.excluded.csi300_nav,
            "sp500_nav": stmt.excluded.sp500_nav,
            "nasdaq_nav": stmt.excluded.nasdaq_nav,
            # review_notes 不在 set_ 中：清算不覆盖人工日记
        },
    )
    await session.execute(stmt)


def allocation_summary(
    valuations: list[PositionValuation],
) -> dict[str, Decimal]:
    """按资产大类汇总市值占比（asset_class -> 0~1）。"""
    total = sum((v.market_value_cny for v in valuations), ZERO)
    if total == ZERO:
        return {}
    out: dict[str, Decimal] = {}
    for v in valuations:
        key = v.asset.asset_class
        out[key] = out.get(key, ZERO) + v.market_value_cny
    return {k: (v / total).quantize(Q4) for k, v in out.items()}
