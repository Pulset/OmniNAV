"""历史回补 CLI：

    python -m app.jobs.backfill --from 2026-01-01 [--to 2026-09-01]

1. 全量抓取持仓 MARKET 标的 + 双基准 + 汇率的历史日线
2. 从首笔交易日起逐日重放 NAV 清算，幂等写入快照（覆盖更新）
"""

import argparse
import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import DimAsset, FactTransaction
from app.services.market.akshare_provider import AkshareProvider
from app.services.market.base import ProviderError
from app.services.market.fetcher import _route, upsert_market_rows
from app.services.market.fx_provider import FrankfurterFxProvider
from app.services.settlement import CSI300_SYMBOL, SP500_SYMBOL, run_settlement

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _fetch_history(session, symbols: list[str], start: date, end: date) -> None:
    for symbol in symbols:
        provider = _route(symbol)
        if provider is None:
            logger.warning("符号 %s 无 provider，跳过", symbol)
            continue
        try:
            bars = await asyncio.to_thread(
                provider.fetch_daily, symbol, start, end
            )
            n = await upsert_market_rows(session, symbol, bars)
            logger.info("历史抓取 %s: %d 条", symbol, n)
        except ProviderError as exc:
            logger.error("%s", exc)
    try:
        rows = await FrankfurterFxProvider().fetch_range(start, end)
        for d, symbol, px in rows:
            await upsert_market_rows(session, symbol, [(d, px)])
        logger.info("历史汇率: %d 条", len(rows))
    except ProviderError as exc:
        logger.error("%s", exc)
    await session.commit()


async def run(start: date, end: date) -> None:
    async with SessionLocal() as session:
        assets = (await session.execute(select(DimAsset))).scalars().all()
        market_symbols = [
            a.asset_id for a in assets if a.valuation_type == "MARKET"
        ] + [CSI300_SYMBOL, SP500_SYMBOL]
        await _fetch_history(session, market_symbols, start - timedelta(days=10), end)

        first_txn = (
            await session.execute(select(func.min(FactTransaction.trans_date)))
        ).scalar_one_or_none()
        if first_txn is None:
            logger.info("无交易流水，仅完成行情回补")
            return

        replay_from = max(first_txn, start)
        d = replay_from
        total_days = (end - replay_from).days + 1
        done = 0
        while d <= end:
            result = await run_settlement(session, d, persist=True)
            done += 1
            if done % 30 == 0 or d == end:
                nav = result.nav.unit_nav if result else "—"
                logger.info("回放进度 %d/%d (%s, nav=%s)", done, total_days, d, nav)
            d += timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniNAV 历史回补")
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", default=None)
    args = parser.parse_args()
    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date) if args.to_date else date.today()
    if start > end:
        raise SystemExit("--from 不能晚于 --to")
    asyncio.run(run(start, end))


if __name__ == "__main__":
    main()
