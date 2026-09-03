"""行情与运维入口：手动净值录入、行情查询、Job 手动触发。"""

import inspect
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.core.db import get_session
from app.jobs.scheduler import JOB_REGISTRY
from app.models import DimAsset, FactDailyMarketData, FactManualNav, SysUser
from app.schemas import ManualNavIn, MarketPriceOut
from app.services.market.cache import QuoteCache
from app.services.settlement import mark_settlement_dirty

router = APIRouter(
    prefix="/market", tags=["market"], dependencies=[Depends(get_current_user)]
)


@router.post("/manual-nav/{asset_id}", response_model=MarketPriceOut, status_code=201)
async def upsert_manual_nav(
    asset_id: str,
    payload: ManualNavIn,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """净值型理财（MANUAL_NAV）手动录入最新单位净值（按用户隔离存储）。"""
    asset = await session.get(DimAsset, (user.id, asset_id))
    if not asset:
        raise HTTPException(404, f"资产 {asset_id} 不存在")
    if asset.valuation_type != "MANUAL_NAV":
        raise HTTPException(422, "只有 MANUAL_NAV 估值模式的资产支持手动净值录入")
    stmt = pg_insert(FactManualNav).values(
        user_id=user.id,
        asset_id=asset_id,
        nav_date=payload.nav_date,
        nav=payload.nav,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "asset_id", "nav_date"],
        set_={"nav": stmt.excluded.nav},
    )
    await session.execute(stmt)
    await mark_settlement_dirty(session, user.id, payload.nav_date)
    await session.commit()
    return MarketPriceOut(
        trade_date=payload.nav_date, symbol=asset_id, close_price=payload.nav
    )


@router.get("/prices", response_model=list[MarketPriceOut])
async def latest_prices(
    symbol: str,
    limit: int = Query(default=30, le=500),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(FactDailyMarketData)
            .where(FactDailyMarketData.symbol == symbol)
            .order_by(FactDailyMarketData.trade_date.desc())
            .limit(limit)
        )
    ).scalars().all()
    return rows


@router.post("/jobs/run/{job_name}")
async def run_job_manually(
    job_name: str,
    target_date: date | None = None,
    admin: SysUser = Depends(require_admin),
):
    """手动触发 Job（与定时触发等价），用于调试与补算。

    仅管理员；Redis 运行锁防止与定时触发/其他手动触发并发执行
    （重复推送与快照 upsert 死锁）。锁兜底 TTL 30 分钟防死锁残留。
    """
    job = JOB_REGISTRY.get(job_name)
    if not job:
        raise HTTPException(404, f"未知 Job: {job_name}，可选: {list(JOB_REGISTRY)}")
    cache = QuoteCache()
    lock_key = f"job:{job_name}"
    if not await cache.try_lock(lock_key, ttl_seconds=1800):
        raise HTTPException(409, f"Job {job_name} 正在运行，请稍后再试")
    try:
        kwargs = {}
        if target_date and "target_date" in inspect.signature(job).parameters:
            kwargs["target_date"] = target_date
        await job(**kwargs)
    finally:
        await cache.release_lock(lock_key)
    return {"status": "done", "job": job_name, "target_date": target_date}
