"""06:00 终局清算 Job（设计决策 D1 + MultiUser §5.1）：

行情与汇率全用户共享，全局抓取一次；清算与推送按活跃用户循环，
每用户独立 session（单用户失败不影响他人，也不污染共享事务）。
手动触发（POST /api/market/jobs/run/eod_settlement）等价于定时触发。

清算前先检测回放需求（流水变更的 dirty 标记 / 冷启动链头缺失），
自动从失效日逐日重放到目标日，再推送当日卡片。
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
    clear_settlement_dirty,
    detect_replay_start,
    get_latest_snapshot,
    replay_settlements,
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
        replay_from = await detect_replay_start(session, user.id, target_date)
        if replay_from is not None:
            logger.info(
                "user=%s 清算链失效（自 %s），自动回放至 %s",
                user.id, replay_from, target_date,
            )
            result = await replay_settlements(
                session, user.id, replay_from, target_date
            )
            await clear_settlement_dirty(session, user.id)
            await session.commit()
        else:
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

    book = await _load_price_book(session, target_date, user_id=user.id)
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
    if target_date.weekday() >= 5:
        # 周末全球无交易：跳过清算，避免零信息快照与重复推送污染统计
        logger.info("目标日 %s 为周末，跳过清算", target_date)
        return
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
            async with SessionLocal() as session:
                await _settle_for_user(session, user, target_date)
        except Exception:
            logger.exception("user=%s(%s) 终局清算失败，跳过", user.id, user.username)
    logger.info("终局清算结束: %s", target_date)
