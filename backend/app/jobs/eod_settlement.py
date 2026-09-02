"""06:00 终局清算 Job（设计决策 D1）：

美股已收盘 → 抓取全市场终值 + 汇率 → 固收计息 → NAV 权威快照 → 告警评估
→ 推送全量复盘卡片。手动触发（POST /api/jobs/run/eod_settlement）等价于定时触发。
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import FactPortfolioSnapshot
from app.services.alerts import AlertEvent, evaluate_eod_alerts
from app.services.market.fetcher import fetch_latest_market_data
from app.services.notify import notify_all
from app.services.report import build_daily_card
from app.services.settlement import (
    get_latest_snapshot,
    run_settlement,
)
from app.services.valuation import MissingPriceError

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


async def _latest_review_note(session: AsyncSession, up_to: date) -> str | None:
    snap = (
        await session.execute(
            select(FactPortfolioSnapshot)
            .where(
                FactPortfolioSnapshot.snapshot_date <= up_to,
                FactPortfolioSnapshot.review_notes.is_not(None),
            )
            .order_by(FactPortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return snap.review_notes if snap else None


async def eod_settlement_job(target_date: date | None = None) -> None:
    if target_date is None:
        target_date = datetime.now(CST).date() - timedelta(days=1)
    logger.info("终局清算开始: %s", target_date)
    async with SessionLocal() as session:
        try:
            await fetch_latest_market_data(session, target_date)
            result = await run_settlement(session, target_date, persist=True)
        except MissingPriceError as exc:
            logger.error("终局清算失败: %s", exc)
            await notify_all(
                f"{target_date.isoformat()} 终局清算失败",
                [f"行情/汇率数据缺失：{exc}"],
                alert=True,
            )
            return
        if result is None:
            logger.info("无交易流水，跳过清算")
            return

        from app.services.settlement import _load_price_book

        book = await _load_price_book(session, target_date)
        alerts: list[AlertEvent] = await evaluate_eod_alerts(session, book, result)
        prev_snapshot = await get_latest_snapshot(session, target_date)
        note = await _latest_review_note(session, target_date)

        title, sections = build_daily_card(
            result, prev_snapshot, alerts, note, estimated=False
        )
        await notify_all(title, sections, alert=bool(alerts))
        logger.info("终局清算完成: nav=%s", result.nav.unit_nav)
