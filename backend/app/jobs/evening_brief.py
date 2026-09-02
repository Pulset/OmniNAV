"""22:00 A股日终简报 Job（设计决策 D1）：

A/港股用当日收盘终值，美股以最近可得价格估算，计算预估净值并推送简报卡片。
不落正式快照——权威快照由次日 06:00 终局清算生成。
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.db import SessionLocal
from app.services.market.fetcher import fetch_latest_market_data
from app.services.notify import notify_all
from app.services.report import build_daily_card
from app.services.settlement import get_latest_snapshot, run_settlement
from app.services.valuation import MissingPriceError

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


async def evening_brief_job(target_date: date | None = None) -> None:
    if target_date is None:
        target_date = datetime.now(CST).date()
    logger.info("A股日终简报开始: %s", target_date)
    async with SessionLocal() as session:
        try:
            await fetch_latest_market_data(session, target_date)
            result = await run_settlement(session, target_date, persist=False)
        except MissingPriceError as exc:
            logger.error("日终简报失败: %s", exc)
            return
        if result is None:
            logger.info("无交易流水，跳过简报")
            return
        prev_snapshot = await get_latest_snapshot(session, target_date)
        title, sections = build_daily_card(
            result, prev_snapshot, [], None, estimated=True
        )
        await notify_all(title, sections)
        logger.info("A股日终简报完成: 预估 nav=%s", result.nav.unit_nav)
