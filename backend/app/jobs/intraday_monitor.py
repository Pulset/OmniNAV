"""盘中微监控 Job：交易日 09:30–23:00 每 15 分钟轮询持仓实时行情（MultiUser §5.1）。

行情簿全局载入一次；监控与推送按活跃用户循环，告警去重锁带用户前缀
（intraday:{user_id}:{asset_id}），单用户失败不中断他人。
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import DimAsset, FactTransaction, SysAlertRule, SysUser
from app.services.market.cache import QuoteCache
from app.services.nav import ZERO
from app.services.notify import notify_user
from app.services.portfolio import aggregate_holdings
from app.services.settlement import _load_price_book
from app.services.valuation import PriceBook

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")
Q4 = Decimal("0.0001")

_WINDOW_START = time(9, 30)
_WINDOW_END = time(23, 0)


async def _fetch_realtime(symbol: str) -> Decimal | None:
    """实时价：A股走 AkShare 买卖五档快照，港股/美股走 yfinance。"""
    if symbol.endswith((".SH", ".SZ")):
        def _ak():
            import akshare as ak

            code = symbol.split(".")[0]
            df = ak.stock_bid_ask_em(symbol=code)
            row = df[df["item"] == "最新"]
            if not row.empty:
                return Decimal(str(row.iloc[0]["value"]))
            return None

        try:
            return await asyncio.to_thread(_ak)
        except Exception:
            logger.debug("AkShare 实时 %s 失败", symbol, exc_info=True)
            return None

    from app.services.market.yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    return await asyncio.to_thread(provider.fetch_realtime, symbol)


async def _monitor_for_user(
    session: AsyncSession,
    user: SysUser,
    book: PriceBook,
    cache: QuoteCache,
    now: datetime,
) -> None:
    rules = (
        (
            await session.execute(
                select(SysAlertRule).where(
                    SysAlertRule.user_id == user.id,
                    SysAlertRule.is_active.is_(True),
                    SysAlertRule.rule_type == "DAILY_PCT_CHANGE",
                    SysAlertRule.asset_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rules:
        return

    txns = (
        (
            await session.execute(
                select(FactTransaction).where(FactTransaction.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    holdings = aggregate_holdings(txns)
    if not holdings:
        return
    assets = {
        a.asset_id: a
        for a in (
            await session.execute(
                select(DimAsset).where(DimAsset.user_id == user.id)
            )
        ).scalars()
    }

    alerts: list[str] = []
    for rule in rules:
        asset_id = rule.asset_id
        if asset_id not in holdings or asset_id not in assets:
            continue
        asset = assets[asset_id]
        price = await cache.get_quote(asset_id)
        if price is None:
            price = await _fetch_realtime(asset_id)
        if price is None:
            continue
        await cache.set_quote(asset_id, price)

        # 基准固定取「昨收」：显式回看一天，避免 22:00 简报写入当日收盘后
        # 基准变成当日收盘导致涨跌幅恒为 0、告警失效
        prev = book.close(asset_id, now.date() - timedelta(days=1))
        if prev is None or prev == ZERO:
            continue
        pct = (price / prev - 1).quantize(Q4, ROUND_HALF_UP)
        threshold = Decimal(rule.threshold)
        if abs(pct) >= threshold:
            locked = await cache.try_lock(f"intraday:{user.id}:{asset_id}")
            if locked:
                alerts.append(
                    f"{asset.name}({asset_id}) 盘中 {pct:+.2%}，"
                    f"触发阈值 ±{threshold:.0%}（现价 {price}）"
                )

    if alerts:
        await notify_user(
            session,
            user.id,
            f"{now.date().isoformat()} 盘中异动告警",
            [f"🚨 **{a}**" for a in alerts],
            alert=True,
        )


async def intraday_monitor_job() -> None:
    now = datetime.now(CST)
    if now.weekday() >= 5 or not (_WINDOW_START <= now.time() <= _WINDOW_END):
        return

    async with SessionLocal() as session:
        book = await _load_price_book(session, now.date())
        users = (
            (
                await session.execute(
                    select(SysUser).where(SysUser.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
    cache = QuoteCache()
    for user in users:
        try:
            async with SessionLocal() as session:
                await _monitor_for_user(session, user, book, cache, now)
        except Exception:
            logger.exception("user=%s(%s) 盘中监控失败，跳过", user.id, user.username)
