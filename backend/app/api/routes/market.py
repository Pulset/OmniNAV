"""行情与运维入口：手动净值录入、行情查询、Job 手动触发。"""

import inspect
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.jobs.scheduler import JOB_REGISTRY
from app.models import DimAsset, FactDailyMarketData
from app.schemas import ManualNavIn, MarketPriceOut
from app.services.market.fetcher import upsert_market_rows

router = APIRouter(prefix="/market", tags=["market"])


@router.post("/manual-nav/{asset_id}", response_model=MarketPriceOut, status_code=201)
async def upsert_manual_nav(
    asset_id: str,
    payload: ManualNavIn,
    session: AsyncSession = Depends(get_session),
):
    """净值型理财（MANUAL_NAV）手动录入最新单位净值。"""
    asset = await session.get(DimAsset, asset_id)
    if not asset:
        raise HTTPException(404, f"资产 {asset_id} 不存在")
    if asset.valuation_type != "MANUAL_NAV":
        raise HTTPException(422, "只有 MANUAL_NAV 估值模式的资产支持手动净值录入")
    await upsert_market_rows(session, asset_id, [(payload.nav_date, payload.nav)])
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
):
    """手动触发 Job（与定时触发等价），用于调试与补算。"""
    job = JOB_REGISTRY.get(job_name)
    if not job:
        raise HTTPException(404, f"未知 Job: {job_name}，可选: {list(JOB_REGISTRY)}")
    kwargs = {}
    if target_date and "target_date" in inspect.signature(job).parameters:
        kwargs["target_date"] = target_date
    await job(**kwargs)
    return {"status": "done", "job": job_name, "target_date": target_date}
