"""AI 投资内参 Job（三时点）：盘前 08:45 / 午间 11:45 / 晚间 21:30。

流程：刷新行情（盘前/晚间）→ 抓取新闻入库 → 按活跃用户逐个生成内参并推送。
LLM 未配置时整体跳过；非交易日跳过（交易日历，失败退化为周末判断）。
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import SysUser
from app.services.advisor import (
    SLOT_NOMINAL_TIME,
    AdvicePayload,
    Slot,
    build_advice_card,
    generate_for_user,
)
from app.services.market.cache import QuoteCache
from app.services.market.fetcher import fetch_latest_market_data
from app.services.news import fetch_and_store_news
from app.services.notify import notify_user
from app.services.trade_calendar import is_trading_day

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


def llm_configured() -> bool:
    s = get_settings()
    return bool(s.llm_base_url and s.llm_api_key and s.llm_model)


async def advisor_job(slot: Slot, target_date: date | None = None) -> None:
    s = get_settings()
    if not s.news_advisor_enabled:
        logger.info("AI 内参未启用（NEWS_ADVISOR_ENABLED=false），跳过 %s", slot)
        return
    if not llm_configured():
        logger.warning("LLM 未配置（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL），跳过 %s", slot)
        return
    today = datetime.now(CST).date()
    target_date = target_date or today
    if not await is_trading_day(target_date):
        logger.info("%s 非交易日，跳过 %s 内参", target_date, slot)
        return
    now = (
        datetime.now(CST)
        if target_date == today
        else datetime.combine(target_date, SLOT_NOMINAL_TIME[slot], tzinfo=CST)
    )
    logger.info("AI 内参生成开始: %s %s", target_date, slot)

    async with SessionLocal() as session:
        # 盘前需隔夜美股收盘、晚间需当日 A股收盘；午间不刷库（实时价走
        # fetch_realtime，避免把盘中半根日K写进行情表）
        if slot in ("morning", "evening"):
            await fetch_latest_market_data(session, target_date)
        await fetch_and_store_news(session)
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
                report = await generate_for_user(
                    session, user, target_date, slot, now=now, cache=cache
                )
                if report is None:
                    continue
                payload = AdvicePayload.model_validate(report.payload)
                title, sections = build_advice_card(target_date, slot, payload)
                await notify_user(session, user.id, title, sections)
                logger.info(
                    "user=%s %s 内参完成: 引用 %s 条新闻",
                    user.id, slot, len(report.cited_article_ids or []),
                )
        except Exception:
            logger.exception(
                "user=%s(%s) %s 内参生成失败，跳过", user.id, user.username, slot
            )
    logger.info("AI 内参生成结束: %s %s", target_date, slot)


async def advisor_morning_job(target_date: date | None = None) -> None:
    await advisor_job("morning", target_date)


async def advisor_midday_job(target_date: date | None = None) -> None:
    await advisor_job("midday", target_date)


async def advisor_evening_job(target_date: date | None = None) -> None:
    await advisor_job("evening", target_date)
