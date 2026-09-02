"""告警规则 CRUD（sys_alert_rules）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import DimAsset, SysAlertRule
from app.schemas import AlertRuleCreate, AlertRuleOut, AlertRuleUpdate

router = APIRouter(prefix="/alert-rules", tags=["alerts"])


@router.get("", response_model=list[AlertRuleOut])
async def list_rules(session: AsyncSession = Depends(get_session)):
    return (
        await session.execute(select(SysAlertRule).order_by(SysAlertRule.id))
    ).scalars().all()


@router.post("", response_model=AlertRuleOut, status_code=201)
async def create_rule(
    payload: AlertRuleCreate, session: AsyncSession = Depends(get_session)
):
    if payload.asset_id and not await session.get(DimAsset, payload.asset_id):
        raise HTTPException(404, f"资产 {payload.asset_id} 不存在")
    rule = SysAlertRule(**payload.model_dump())
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    session: AsyncSession = Depends(get_session),
):
    rule = await session.get(SysAlertRule, rule_id)
    if not rule:
        raise HTTPException(404, f"规则 {rule_id} 不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    rule = await session.get(SysAlertRule, rule_id)
    if not rule:
        raise HTTPException(404, f"规则 {rule_id} 不存在")
    await session.delete(rule)
    await session.commit()
