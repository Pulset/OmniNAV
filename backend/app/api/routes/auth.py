"""认证与会话：登录/登出/当前用户/改密/个人通知渠道（MultiUser §3.3）。"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import security
from app.core.config import get_settings
from app.core.db import get_session
from app.models import SysUser, UserSetting
from app.schemas.user import (
    LoginIn,
    NotificationsIn,
    NotificationsOut,
    PasswordChangeIn,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_brief(user: SysUser) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/login")
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    ip = request.client.host if request.client else "unknown"
    if await security.is_login_blocked(payload.username, ip):
        raise HTTPException(429, "失败次数过多，请 15 分钟后重试")
    user = (
        await session.execute(
            select(SysUser).where(SysUser.username == payload.username)
        )
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not security.verify_password(user.password_hash, payload.password)
    ):
        await security.register_login_fail(payload.username, ip)
        raise HTTPException(401, "用户名或密码错误")

    await security.reset_login_fails(payload.username, ip)
    token = await security.create_session(user.id)
    response.set_cookie(
        security.SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=security.SESSION_TTL_SECONDS,
        path="/",
    )
    return _user_brief(user)


@router.post("/logout")
async def logout(
    response: Response,
    omninav_session: str | None = Cookie(default=None),
):
    if omninav_session:
        await security.revoke_session(omninav_session)
    response.delete_cookie(security.SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: SysUser = Depends(get_current_user)):
    return _user_brief(user)


@router.put("/me/password")
async def change_password(
    payload: PasswordChangeIn,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not security.verify_password(user.password_hash, payload.old_password):
        raise HTTPException(422, "原密码不正确")
    user.password_hash = security.hash_password(payload.new_password)
    await session.commit()
    # 全量吊销（含当前会话），前端统一跳回登录页
    await security.revoke_all_user_sessions(user.id)
    return {"ok": True}


@router.get("/me/notifications", response_model=NotificationsOut)
async def get_notifications(
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(UserSetting, user.id)
    if row is None:
        return NotificationsOut()
    return NotificationsOut(
        feishu_webhook_url=row.feishu_webhook_url,
        telegram_bot_token=row.telegram_bot_token,
        telegram_chat_id=row.telegram_chat_id,
    )


@router.put("/me/notifications", response_model=NotificationsOut)
async def update_notifications(
    payload: NotificationsIn,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(UserSetting, user.id)
    if row is None:
        row = UserSetting(user_id=user.id, **payload.model_dump())
        session.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    await session.commit()
    return NotificationsOut(**payload.model_dump())
