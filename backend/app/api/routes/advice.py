"""AI 投资内参入口：三时点内参查询、手动重新生成、新闻池查询。"""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.jobs.news_advisor import llm_configured
from app.models import FactAdviceReport, FactNewsArticle, SysUser
from app.schemas import AdviceGenerateIn, AdviceReportOut, NewsArticleOut
from app.services.market.cache import QuoteCache

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")

router = APIRouter(
    prefix="/advice", tags=["advice"], dependencies=[Depends(get_current_user)]
)


@router.get("/latest", response_model=AdviceReportOut | None)
async def latest_advice(
    slot: str = Query(pattern="^(morning|midday|evening)$"),
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """当前用户指定时点的最新一期内参（无则 null）。"""
    report = (
        await session.execute(
            select(FactAdviceReport)
            .where(FactAdviceReport.user_id == user.id, FactAdviceReport.slot == slot)
            .order_by(FactAdviceReport.trade_date.desc(), FactAdviceReport.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return report


@router.get("", response_model=list[AdviceReportOut])
async def advice_history(
    days: int = Query(default=30, ge=1, le=365),
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    since = date.today() - timedelta(days=days)
    return (
        (
            await session.execute(
                select(FactAdviceReport)
                .where(
                    FactAdviceReport.user_id == user.id,
                    FactAdviceReport.trade_date >= since,
                )
                .order_by(FactAdviceReport.trade_date.desc(), FactAdviceReport.slot)
            )
        )
        .scalars()
        .all()
    )


@router.post("/generate", response_model=AdviceReportOut, status_code=201)
async def generate_advice(
    payload: AdviceGenerateIn,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """为当前用户手动生成/重算指定时点内参（Redis 锁限频防连点）。"""
    from app.services.advisor import generate_for_user

    if not llm_configured():
        raise HTTPException(
            503, "LLM 未配置（backend/.env 设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）"
        )
    cache = QuoteCache()
    if not await cache.try_lock(
        f"advice-gen:{user.id}:{payload.slot}", ttl_seconds=300
    ):
        raise HTTPException(429, "该时点内参正在生成中，请 5 分钟后再试")
    try:
        trade_date = payload.trade_date or datetime.now(CST).date()
        report = await generate_for_user(
            session, user, trade_date, payload.slot, cache=cache
        )
        if report is None:
            raise HTTPException(
                422, "该时间窗内暂无新闻素材，无法生成（非交易日或新闻源未更新）"
            )
        return report
    finally:
        await cache.release_lock(f"advice-gen:{user.id}:{payload.slot}")


@router.get("/news", response_model=list[NewsArticleOut])
async def news_list(
    d: date | None = None,
    limit: int = Query(default=60, ge=1, le=200),
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """新闻池（默认今天；供内参溯源与浏览）。"""
    d = d or datetime.now(CST).date()
    start = datetime.combine(d, time(0, 0), tzinfo=CST)
    end = start + timedelta(days=1)
    return (
        (
            await session.execute(
                select(FactNewsArticle)
                .where(
                    FactNewsArticle.published_at >= start,
                    FactNewsArticle.published_at < end,
                )
                .order_by(FactNewsArticle.published_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
