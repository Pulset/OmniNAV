"""盘中微监控 Job：交易日 09:30–23:00 每 15 分钟轮询持仓实时行情。

命中 DAILY_PCT_CHANGE 告警阈值即推送（Redis 锁保证单标的当日只推一次）。
"""

import asyncio
import logging
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import DimAsset, FactTransaction, SysAlertRule
from app.services.market.cache import QuoteCache
from app.services.nav import ZERO
from app.services.notify import notify_all
from app.services.portfolio import aggregate_holdings
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


async def _load_realtime_book(session: AsyncSession) -> PriceBook:
    from app.services.settlement import _load_price_book
    from datetime import date

    return await _load_price_book(session, date.today())


async def intraday_monitor_job() -> None:
    now = datetime.now(CST)
    if now.weekday() >= 5 or not (_WINDOW_START <= now.time() <= _WINDOW_END):
        return

    async with SessionLocal() as session:
        rules = (
            (
                await session.execute(
                    select(SysAlertRule).where(
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

        txns = (await session.execute(select(FactTransaction))).scalars().all()
        holdings = aggregate_holdings(txns)
        if not holdings:
            return
        assets = {
            a.asset_id: a
            for a in (await session.execute(select(DimAsset))).scalars()
        }

        book = await _load_realtime_book(session)
        cache = QuoteCache()
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

            prev = book.close(asset_id, datetime.now(CST).date())
            if prev is None or prev == ZERO:
                continue
            pct = (price / prev - 1).quantize(Q4, ROUND_HALF_UP)
            threshold = Decimal(rule.threshold)
            if abs(pct) >= threshold:
                locked = await cache.try_lock(f"intraday:{asset_id}")
                if locked:
                    alerts.append(
                        f"{asset.name}({asset_id}) 盘中 {pct:+.2%}，"
                        f"触发阈值 ±{threshold:.0%}（现价 {price}）"
                    )

        if alerts:
            await notify_all(
                f"{now.date().isoformat()} 盘中异动告警",
                [f"🚨 **{a}**" for a in alerts],
                alert=True,
            )
