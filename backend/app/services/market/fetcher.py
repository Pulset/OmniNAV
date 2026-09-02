"""行情抓取编排：路由到 provider → 幂等写入 fact_daily_market_data。"""

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DimAsset, FactDailyMarketData, FactTransaction
from app.services.market.akshare_provider import AkshareProvider
from app.services.market.base import DailyBars, ProviderError
from app.services.market.fx_provider import FrankfurterFxProvider
from app.services.market.yfinance_provider import YFinanceProvider
from app.services.settlement import CSI300_SYMBOL, SP500_SYMBOL

logger = logging.getLogger(__name__)

_PROVIDERS = (AkshareProvider(), YFinanceProvider())


def _route(symbol: str):
    for p in _PROVIDERS:
        if p.supports(symbol):
            return p
    return None


async def upsert_market_rows(
    session: AsyncSession, symbol: str, bars: DailyBars
) -> int:
    if not bars:
        return 0
    stmt = pg_insert(FactDailyMarketData).values(
        [{"trade_date": d, "symbol": symbol, "close_price": px} for d, px in bars]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["trade_date", "symbol"],
        set_={"close_price": stmt.excluded.close_price},
    )
    await session.execute(stmt)
    return len(bars)


async def held_market_symbols(session: AsyncSession) -> list[str]:
    """当前有持仓流水的 MARKET 资产符号 + 双基准指数。"""
    asset_ids = (
        (await session.execute(select(FactTransaction.asset_id).distinct()))
        .scalars()
        .all()
    )
    if not asset_ids:
        return [CSI300_SYMBOL, SP500_SYMBOL]
    assets = {
        a.asset_id: a
        for a in (
            await session.execute(
                select(DimAsset).where(DimAsset.asset_id.in_(asset_ids))
            )
        ).scalars()
    }
    symbols = [
        aid
        for aid in asset_ids
        if aid in assets and assets[aid].valuation_type == "MARKET"
    ]
    return symbols + [CSI300_SYMBOL, SP500_SYMBOL]


async def fetch_latest_market_data(session: AsyncSession, as_of: date) -> None:
    """终局清算前的增量抓取：近期窗口内全部持仓标的 + 基准 + 汇率。"""
    start = as_of - timedelta(days=10)
    for symbol in await held_market_symbols(session):
        provider = _route(symbol)
        if provider is None:
            logger.warning("符号 %s 没有可用行情 provider，跳过", symbol)
            continue
        try:
            bars = await asyncio.to_thread(provider.fetch_daily, symbol, start, as_of)
            n = await upsert_market_rows(session, symbol, bars)
            logger.info("抓取 %s: %d 条 (至 %s)", symbol, n, as_of)
        except ProviderError as exc:
            logger.error("%s", exc)

    try:
        rows = await FrankfurterFxProvider().fetch_range(start, as_of)
        for d, symbol, px in rows:
            await upsert_market_rows(session, symbol, [(d, px)])
        logger.info("抓取汇率: %d 条", len(rows))
    except ProviderError as exc:
        logger.error("%s", exc)
    await session.commit()
