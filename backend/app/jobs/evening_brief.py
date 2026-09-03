"""22:00 A股日终简报 Job（设计决策 D1 + MultiUser §5.1）：

A/港股用当日收盘终值，美股以最近可得价格估算，计算预估净值并按用户推送简报卡片。
不落正式快照——权威快照由次日 06:00 终局清算生成。

推送前先回放修复历史脏链（persist，不含当日），保证预估净值基于正确链基。
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import SysUser
from app.services.market.fetcher import fetch_latest_market_data
from app.services.notify import notify_user
from app.services.report import build_daily_card
from app.services.settlement import (
    ensure_chain_current,
    get_latest_snapshot,
    run_settlement,
)
from app.services.valuation import MissingPriceError

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


async def _brief_for_user(
    session, user: SysUser, target_date: date
) -> None:
    try:
        await ensure_chain_current(session, user.id, target_date)
        result = await run_settlement(
            session, target_date, user_id=user.id, persist=False
        )
    except MissingPriceError as exc:
        logger.error("user=%s 日终简报失败: %s", user.id, exc)
        return
    if result is None:
        logger.info("user=%s 无交易流水，跳过简报", user.id)
        return
    prev_snapshot = await get_latest_snapshot(session, user.id, target_date)
    title, sections = build_daily_card(
        result, prev_snapshot, [], None, estimated=True
    )
    await notify_user(session, user.id, title, sections)
    logger.info("user=%s 日终简报完成: 预估 nav=%s", user.id, result.nav.unit_nav)


async def evening_brief_job(target_date: date | None = None) -> None:
    if target_date is None:
        target_date = datetime.now(CST).date()
    if target_date.weekday() >= 5:
        logger.info("目标日 %s 为周末，跳过日终简报", target_date)
        return
    logger.info("A股日终简报开始: %s", target_date)
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
            async with SessionLocal() as session:
                await _brief_for_user(session, user, target_date)
        except Exception:
            logger.exception("user=%s(%s) 日终简报失败，跳过", user.id, user.username)
    logger.info("A股日终简报结束: %s", target_date)
