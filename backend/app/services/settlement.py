"""每日清算编排：加载流水/行情 → 估值 → NAV 核算 → 快照 upsert。

同时服务三处调用：06:00 终局清算（persist=True）、22:00 预估简报
（persist=False）、历史回放回补（逐日 persist=True，幂等覆盖）。
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DimAsset, FactDailyMarketData, FactPortfolioSnapshot, FactTransaction
from app.services.nav import Q2, Q4, ZERO, NavResult, settle_day
from app.services.portfolio import aggregate_diluted_cost, aggregate_holdings, net_cash_flow_cny
from app.services.valuation import (
    AssetLike,
    PositionValuation,
    PriceBook,
    value_asset,
)

logger = logging.getLogger(__name__)

CSI300_SYMBOL = "CSI300"
SP500_SYMBOL = "SP500"
NASDAQ_SYMBOL = "NASDAQ"


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


async def _load_price_book(session: AsyncSession, up_to: date) -> PriceBook:
    rows = (
        await session.execute(
            select(
                FactDailyMarketData.trade_date,
                FactDailyMarketData.symbol,
                FactDailyMarketData.close_price,
            ).where(FactDailyMarketData.trade_date <= up_to)
        )
    ).all()
    return PriceBook(rows)


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


def _normalized_benchmark(
    book: PriceBook, symbol: str, base_date: date, target: date
) -> Decimal | None:
    base = book.close(symbol, base_date)
    cur = book.close(symbol, target)
    if not base or base == ZERO or not cur:
        return None
    return (cur / base).quantize(Q4, ROUND_HALF_UP)


async def run_settlement(
    session: AsyncSession, target_date: date, *, user_id: int, persist: bool = True
) -> SettlementResult | None:
    """对 target_date 执行某用户的 NAV 清算。该用户无任何流水时返回 None。"""
    txns = (
        (
            await session.execute(
                select(FactTransaction)
                .where(
                    FactTransaction.user_id == user_id,
                    FactTransaction.trans_date <= target_date,
                )
                .order_by(FactTransaction.trans_date, FactTransaction.id)
            )
        )
        .scalars()
        .all()
    )
    if not txns:
        return None

    assets = {
        a.asset_id: _to_asset_like(a)
        for a in (
            await session.execute(
                select(DimAsset).where(DimAsset.user_id == user_id)
            )
        ).scalars()
    }

    book = await _load_price_book(session, target_date)
    holdings_today = aggregate_holdings(txns)
    holdings_before = aggregate_holdings(
        [t for t in txns if t.trans_date < target_date]
    )
    diluted = aggregate_diluted_cost(txns)

    def _value_all(holdings: dict[str, list]) -> list[PositionValuation]:
        return [
            value_asset(
                assets[aid],
                lots,
                book,
                target_date,
                diluted_cost=diluted.get(aid),
            )
            for aid, lots in holdings.items()
            if aid in assets
        ]

    valuations = _value_all(holdings_today)
    valuations_before_flow = _value_all(holdings_before)

    mv_today = sum((v.market_value_cny for v in valuations), ZERO)
    mv_before_flow = sum((v.market_value_cny for v in valuations_before_flow), ZERO)

    flow = net_cash_flow_cny(
        [t for t in txns if t.trans_date == target_date],
        lambda cur, d: book.fx_to_cny(cur, d),
    )

    prev = await get_latest_snapshot(session, user_id, target_date)
    yesterday_nav = Decimal(prev.unit_nav) if prev else ZERO
    yesterday_shares = Decimal(prev.total_shares) if prev else ZERO
    yesterday_mv = Decimal(prev.total_market_value_cny) if prev else ZERO

    nav = settle_day(
        yesterday_nav=yesterday_nav,
        yesterday_shares=yesterday_shares,
        yesterday_total_mv=yesterday_mv,
        today_mv_before_flow=mv_before_flow,
        today_mv_end_of_day=mv_today,
        today_net_cash_flow=flow,
    )

    # 基准指数归一化：以该用户组合首个快照日（无则当日）为 1.0000 基点
    base_date = (await get_first_snapshot_date(session, user_id)) or target_date
    csi300_nav = _normalized_benchmark(book, CSI300_SYMBOL, base_date, target_date)
    sp500_nav = _normalized_benchmark(book, SP500_SYMBOL, base_date, target_date)
    nasdaq_nav = _normalized_benchmark(book, NASDAQ_SYMBOL, base_date, target_date)

    if persist:
        await _upsert_snapshot(
            session,
            user_id,
            target_date,
            mv_today=mv_today,
            nav=nav,
            csi300_nav=csi300_nav,
            sp500_nav=sp500_nav,
            nasdaq_nav=nasdaq_nav,
        )
        await session.commit()

    return SettlementResult(
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
        persisted=persist,
    )


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
