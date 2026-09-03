"""鉴权依赖（MultiUser §3.4）：所有业务路由的唯一切换点，未来对接 OIDC 只改这里。"""

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.db import get_session
from app.models import SysUser


async def get_current_user(
    omninav_session: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> SysUser:
    if not omninav_session:
        raise HTTPException(401, "未登录")
    user_id = await security.get_session_user(omninav_session)
    if user_id is None:
        raise HTTPException(401, "会话已失效，请重新登录")
    user = await session.get(SysUser, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "账号不可用")
    return user


async def require_admin(user: SysUser = Depends(get_current_user)) -> SysUser:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
