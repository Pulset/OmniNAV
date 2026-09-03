"""告警规则 CRUD（sys_alert_rules）。数据按用户隔离。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import DimAsset, SysAlertRule, SysUser
from app.schemas import AlertRuleCreate, AlertRuleOut, AlertRuleUpdate

router = APIRouter(
    prefix="/alert-rules", tags=["alerts"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[AlertRuleOut])
async def list_rules(
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        await session.execute(
            select(SysAlertRule)
            .where(SysAlertRule.user_id == user.id)
            .order_by(SysAlertRule.id)
        )
    ).scalars().all()


@router.post("", response_model=AlertRuleOut, status_code=201)
async def create_rule(
    payload: AlertRuleCreate,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if payload.asset_id and not await session.get(
        DimAsset, (user.id, payload.asset_id)
    ):
        raise HTTPException(404, f"资产 {payload.asset_id} 不存在")
    rule = SysAlertRule(user_id=user.id, **payload.model_dump())
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rule = await _get_own_rule(session, user, rule_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rule = await _get_own_rule(session, user, rule_id)
    await session.delete(rule)
    await session.commit()


async def _get_own_rule(
    session: AsyncSession, user: SysUser, rule_id: int
) -> SysAlertRule:
    rule = await session.get(SysAlertRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(404, f"规则 {rule_id} 不存在")
    return rule
