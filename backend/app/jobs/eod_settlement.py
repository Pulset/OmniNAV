"""06:00 终局清算 Job（设计决策 D1 + MultiUser §5.1）：

行情与汇率全用户共享，全局抓取一次；清算与推送按活跃用户循环，
单用户失败不中断他人。手动触发（POST /api/market/jobs/run/eod_settlement）
等价于定时触发。
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import FactPortfolioSnapshot, SysUser
from app.services.alerts import AlertEvent, evaluate_eod_alerts
from app.services.market.fetcher import fetch_latest_market_data
from app.services.notify import notify_user
from app.services.report import build_daily_card
from app.services.settlement import (
    _load_price_book,
    get_latest_snapshot,
    run_settlement,
)
from app.services.valuation import MissingPriceError

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


async def _latest_review_note(
    session: AsyncSession, user_id: int, up_to: date
) -> str | None:
    snap = (
        await session.execute(
            select(FactPortfolioSnapshot)
            .where(
                FactPortfolioSnapshot.user_id == user_id,
                FactPortfolioSnapshot.snapshot_date <= up_to,
                FactPortfolioSnapshot.review_notes.is_not(None),
            )
            .order_by(FactPortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return snap.review_notes if snap else None


async def _settle_for_user(
    session: AsyncSession, user: SysUser, target_date: date
) -> None:
    try:
        result = await run_settlement(
            session, target_date, user_id=user.id, persist=True
        )
    except MissingPriceError as exc:
        logger.error("user=%s 终局清算失败: %s", user.id, exc)
        await notify_user(
            session,
            user.id,
            f"{target_date.isoformat()} 终局清算失败",
            [f"行情/汇率数据缺失：{exc}"],
            alert=True,
        )
        return
    if result is None:
        logger.info("user=%s 无交易流水，跳过清算", user.id)
        return

    book = await _load_price_book(session, target_date)
    alerts: list[AlertEvent] = await evaluate_eod_alerts(
        session, user.id, book, result
    )
    prev_snapshot = await get_latest_snapshot(session, user.id, target_date)
    note = await _latest_review_note(session, user.id, target_date)

    title, sections = build_daily_card(
        result, prev_snapshot, alerts, note, estimated=False
    )
    await notify_user(session, user.id, title, sections, alert=bool(alerts))
    logger.info("user=%s 终局清算完成: nav=%s", user.id, result.nav.unit_nav)


async def eod_settlement_job(target_date: date | None = None) -> None:
    if target_date is None:
        target_date = datetime.now(CST).date() - timedelta(days=1)
    logger.info("终局清算开始: %s", target_date)
    async with SessionLocal() as session:
        await fetch_latest_market_data(session, target_date)
        users = (
            (
                await session.execute(
                    select(SysUser).where(SysUser.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for user in users:
            try:
                await _settle_for_user(session, user, target_date)
            except Exception:
                logger.exception("user=%s(%s) 终局清算失败，跳过", user.id, user.username)
    logger.info("终局清算结束: %s", target_date)
