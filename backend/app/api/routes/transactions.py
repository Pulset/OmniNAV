"""交易流水 CRUD（PRD §3.2 极简账本）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import DimAsset, FactTransaction
from app.schemas import TransactionCreate, TransactionOut
from app.schemas.transaction import validate_trans_asset_compat

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    asset_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=200, le=1000),
    session: AsyncSession = Depends(get_session),
):
    q = select(FactTransaction).order_by(
        FactTransaction.trans_date.desc(), FactTransaction.id.desc()
    ).limit(limit)
    if asset_id:
        q = q.where(FactTransaction.asset_id == asset_id)
    if date_from:
        q = q.where(FactTransaction.trans_date >= date_from)
    if date_to:
        q = q.where(FactTransaction.trans_date <= date_to)
    return (await session.execute(q)).scalars().all()


@router.post("", response_model=TransactionOut, status_code=201)
async def create_transaction(
    payload: TransactionCreate, session: AsyncSession = Depends(get_session)
):
    asset = await session.get(DimAsset, payload.asset_id)
    if not asset:
        raise HTTPException(404, f"资产 {payload.asset_id} 不存在，请先创建资产")
    if payload.currency != asset.currency:
        raise HTTPException(
            422,
            f"结算币种 {payload.currency} 与资产币种 {asset.currency} 不一致",
        )
    err = validate_trans_asset_compat(payload, asset.asset_class)
    if err:
        raise HTTPException(422, err)
    txn = FactTransaction(**payload.model_dump())
    session.add(txn)
    await session.commit()
    await session.refresh(txn)
    return txn


@router.put("/{txn_id}", response_model=TransactionOut)
async def update_transaction(
    txn_id: int, payload: TransactionCreate, session: AsyncSession = Depends(get_session)
):
    """全量更新一笔流水，校验规则与新建一致。"""
    txn = await session.get(FactTransaction, txn_id)
    if not txn:
        raise HTTPException(404, f"流水 {txn_id} 不存在")
    asset = await session.get(DimAsset, payload.asset_id)
    if not asset:
        raise HTTPException(404, f"资产 {payload.asset_id} 不存在，请先创建资产")
    if payload.currency != asset.currency:
        raise HTTPException(
            422,
            f"结算币种 {payload.currency} 与资产币种 {asset.currency} 不一致",
        )
    err = validate_trans_asset_compat(payload, asset.asset_class)
    if err:
        raise HTTPException(422, err)
    for key, value in payload.model_dump().items():
        setattr(txn, key, value)
    await session.commit()
    await session.refresh(txn)
    return txn


@router.delete("/{txn_id}", status_code=204)
async def delete_transaction(txn_id: int, session: AsyncSession = Depends(get_session)):
    txn = await session.get(FactTransaction, txn_id)
    if not txn:
        raise HTTPException(404, f"流水 {txn_id} 不存在")
    await session.delete(txn)
    await session.commit()
