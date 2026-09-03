"""管理员用户管理（MultiUser §3.3）：列表 / 建号 / 停用启用 / 重置密码。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core import security
from app.core.db import get_session
from app.models import SysUser
from app.schemas.user import UserCreateIn, UserOut, UserUpdateIn

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("/users", response_model=list[UserOut])
async def list_users(
    admin: SysUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return (
        await session.execute(select(SysUser).order_by(SysUser.id))
    ).scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreateIn,
    admin: SysUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    exists = (
        await session.execute(
            select(SysUser.id).where(SysUser.username == payload.username)
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, f"用户名 {payload.username} 已存在")
    user = SysUser(
        username=payload.username,
        password_hash=security.hash_password(payload.password),
        role=payload.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdateIn,
    admin: SysUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(SysUser, user_id)
    if user is None:
        raise HTTPException(404, f"用户 {user_id} 不存在")
    if payload.is_active is False and user.id == admin.id:
        raise HTTPException(422, "不能停用自己的账号")
    if payload.password is not None:
        user.password_hash = security.hash_password(payload.password)
        await security.revoke_all_user_sessions(user.id)
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            await security.revoke_all_user_sessions(user.id)
    await session.commit()
    await session.refresh(user)
    return user
