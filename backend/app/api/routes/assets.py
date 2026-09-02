"""资产标的 CRUD（PRD §3.1 资产标的管理模块）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import DimAsset, FactTransaction
from app.schemas import AssetCreate, AssetOut, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetOut])
async def list_assets(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(DimAsset).order_by(DimAsset.asset_id))).scalars().all()
    return rows


@router.post("", response_model=AssetOut, status_code=201)
async def create_asset(
    payload: AssetCreate, session: AsyncSession = Depends(get_session)
):
    exists = await session.get(DimAsset, payload.asset_id)
    if exists:
        raise HTTPException(409, f"资产 {payload.asset_id} 已存在")
    asset = DimAsset(**payload.model_dump())
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@router.put("/{asset_id}", response_model=AssetOut)
async def update_asset(
    asset_id: str,
    payload: AssetUpdate,
    session: AsyncSession = Depends(get_session),
):
    asset = await session.get(DimAsset, asset_id)
    if not asset:
        raise HTTPException(404, f"资产 {asset_id} 不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(asset, k, v)
    await session.commit()
    await session.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(asset_id: str, session: AsyncSession = Depends(get_session)):
    asset = await session.get(DimAsset, asset_id)
    if not asset:
        raise HTTPException(404, f"资产 {asset_id} 不存在")
    refs = (
        await session.execute(
            select(FactTransaction.id)
            .where(FactTransaction.asset_id == asset_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if refs is not None:
        raise HTTPException(409, f"资产 {asset_id} 存在关联交易流水，禁止删除")
    await session.delete(asset)
    await session.commit()
