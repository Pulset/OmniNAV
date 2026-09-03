"""交易流水 CRUD（PRD §3.2 极简账本）。数据按用户隔离。

写入口三道防线：
- 资产存在性 / 币种一致 / 类型兼容（原有）
- 超卖校验：全量重放持仓（含本次变更），OverSell 当场 422 拒绝，
  避免坏数据进入后卡死每日清算
- 快照失效标记：变更与 dirty_from 同事务提交，Job 自动逐日回放修复
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import DimAsset, FactTransaction, SysUser
from app.schemas import TransactionCreate, TransactionOut
from app.schemas.transaction import validate_trans_asset_compat
from app.services.portfolio import OverSellError, aggregate_holdings
from app.services.settlement import mark_settlement_dirty

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(get_current_user)],
)


async def _validate_writable(
    session: AsyncSession,
    user: SysUser,
    payload: TransactionCreate | None,
    *,
    replace_txn: FactTransaction | None = None,
) -> None:
    """资产校验 + 全量重放超卖校验。

    payload 为新流水；replace_txn 为被修改/删除的原流水（重放时剔除）。
    payload=None 表示纯删除场景：只重放剔除后的剩余流水。
    """
    if payload is not None:
        asset = await session.get(DimAsset, (user.id, payload.asset_id))
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

    txns = [
        t
        for t in (
            await session.execute(
                select(FactTransaction).where(FactTransaction.user_id == user.id)
            )
        ).scalars()
        if replace_txn is None or t.id != replace_txn.id
    ]
    if payload is not None:
        # 重放按 (trans_date, id) 排序：修改沿用原流水的 id 占位（保持同日时序），
        # 新增用大 id 兜底排在同日已有流水之后，避免同日「先买后卖」误判超卖
        from types import SimpleNamespace

        txns.append(
            SimpleNamespace(
                id=replace_txn.id if replace_txn is not None else 2**62,
                **payload.model_dump(),
            )
        )
    try:
        aggregate_holdings(txns)
    except OverSellError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    asset_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=200, le=1000),
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(FactTransaction)
        .where(FactTransaction.user_id == user.id)
        .order_by(FactTransaction.trans_date.desc(), FactTransaction.id.desc())
        .limit(limit)
    )
    if asset_id:
        q = q.where(FactTransaction.asset_id == asset_id)
    if date_from:
        q = q.where(FactTransaction.trans_date >= date_from)
    if date_to:
        q = q.where(FactTransaction.trans_date <= date_to)
    return (await session.execute(q)).scalars().all()


@router.post("", response_model=TransactionOut, status_code=201)
async def create_transaction(
    payload: TransactionCreate,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _validate_writable(session, user, payload)
    txn = FactTransaction(user_id=user.id, **payload.model_dump())
    session.add(txn)
    await mark_settlement_dirty(session, user.id, payload.trans_date)
    await session.commit()
    await session.refresh(txn)
    return txn


@router.put("/{txn_id}", response_model=TransactionOut)
async def update_transaction(
    txn_id: int,
    payload: TransactionCreate,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """全量更新一笔流水，校验规则与新建一致。"""
    txn = await _get_own_txn(session, user, txn_id)
    await _validate_writable(session, user, payload, replace_txn=txn)
    affected_from = min(txn.trans_date, payload.trans_date)
    for key, value in payload.model_dump().items():
        setattr(txn, key, value)
    await mark_settlement_dirty(session, user.id, affected_from)
    await session.commit()
    await session.refresh(txn)
    return txn


@router.delete("/{txn_id}", status_code=204)
async def delete_transaction(
    txn_id: int,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    txn = await _get_own_txn(session, user, txn_id)
    # 删除买入可能使后续卖出变成超卖，重放剔除后的剩余流水校验
    await _validate_writable(session, user, None, replace_txn=txn)
    await mark_settlement_dirty(session, user.id, txn.trans_date)
    await session.delete(txn)
    await session.commit()


async def _get_own_txn(
    session: AsyncSession, user: SysUser, txn_id: int
) -> FactTransaction:
    txn = await session.get(FactTransaction, txn_id)
    if txn is None or txn.user_id != user.id:
        raise HTTPException(404, f"流水 {txn_id} 不存在")
    return txn
