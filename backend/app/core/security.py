"""密码哈希（argon2id）与 Redis 会话管理（MultiUser §3.2/§8）。

会话 key 约定：
- session:{token}              -> user_id（opaque token，TTL 7 天滑动续期）
- user_sessions:{user_id}      -> token 集合（支持改密/停用时全量吊销）
- login_fail:{username}:{ip}   -> 15 分钟窗口失败计数（限速防爆破）
"""

import secrets

import redis.asyncio as aioredis
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

SESSION_TTL_SECONDS = 7 * 24 * 3600
LOGIN_FAIL_WINDOW_SECONDS = 15 * 60
LOGIN_FAIL_MAX = 5

SESSION_COOKIE_NAME = "omninav_session"

_hasher = PasswordHasher()
_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _redis


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _session_key(token: str) -> str:
    return f"session:{token}"


def _user_sessions_key(user_id: int) -> str:
    return f"user_sessions:{user_id}"


def _login_fail_key(username: str, ip: str) -> str:
    return f"login_fail:{username}:{ip}"


async def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    r = get_redis()
    async with r.pipeline(transaction=True) as pipe:
        pipe.set(_session_key(token), user_id, ex=SESSION_TTL_SECONDS)
        pipe.sadd(_user_sessions_key(user_id), token)
        pipe.expire(_user_sessions_key(user_id), SESSION_TTL_SECONDS + 60)
        await pipe.execute()
    return token


async def get_session_user(token: str) -> int | None:
    """校验 token 并滑动续期；失效返回 None。

    同时续期 user_sessions 集合的 TTL，保证全量吊销集合
    覆盖所有仍有效的 token（集合只在登录时刷新会漏掉续期长寿会话）。
    """
    r = get_redis()
    user_id = await r.get(_session_key(token))
    if user_id is None:
        return None
    async with r.pipeline(transaction=True) as pipe:
        pipe.expire(_session_key(token), SESSION_TTL_SECONDS)
        pipe.expire(
            _user_sessions_key(int(user_id)), SESSION_TTL_SECONDS + 60
        )
        await pipe.execute()
    return int(user_id)


async def revoke_session(token: str) -> None:
    r = get_redis()
    user_id = await r.get(_session_key(token))
    if user_id is None:
        return
    await r.delete(_session_key(token))
    await r.srem(_user_sessions_key(int(user_id)), token)


async def revoke_all_user_sessions(user_id: int) -> None:
    r = get_redis()
    set_key = _user_sessions_key(user_id)
    tokens = await r.smembers(set_key)
    if tokens:
        await r.delete(*(_session_key(t) for t in tokens))
    await r.delete(set_key)


async def is_login_blocked(username: str, ip: str) -> bool:
    count = await get_redis().get(_login_fail_key(username, ip))
    return count is not None and int(count) >= LOGIN_FAIL_MAX


async def register_login_fail(username: str, ip: str) -> None:
    r = get_redis()
    key = _login_fail_key(username, ip)
    await r.incr(key)
    # EXPIRE NX：仅在没有 TTL 时设置（含 incr 后、expire 前崩溃留下的孤儿 key），
    # 已有 TTL 则不刷新窗口，计数到 5 后锁定自然到期解除
    await r.expire(key, LOGIN_FAIL_WINDOW_SECONDS, nx=True)


async def reset_login_fails(username: str, ip: str) -> None:
    await get_redis().delete(_login_fail_key(username, ip))
