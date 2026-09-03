"""pytest 配置：集成测试连本地 Postgres 测试库 + Redis，不可达则跳过相关测试。

- DATABASE_URL 指向测试库（默认 omninav_test，可用 TEST_DATABASE_URL 覆盖）
- 测试专用 engine 使用 NullPool，避免 asyncpg 连接跨事件循环复用
"""

import os

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://omninav_admin:omninav@localhost:5432/omninav_test",
)
TEST_PASSWORD = "password123"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("ENABLE_SCHEDULER", "false")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core import db as appdb  # noqa: E402

_test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
# 路由/Job 均从 app.core.db 取 SessionLocal/engine，替换即可整体切到测试库
appdb.engine = _test_engine
appdb.SessionLocal = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)


async def _prepare_database() -> None:
    import asyncpg

    dsn = TEST_DATABASE_URL.replace("+asyncpg", "")
    dbname = dsn.rsplit("/", 1)[1]
    admin_dsn = dsn.rsplit("/", 1)[0] + "/postgres"
    conn = await asyncpg.connect(admin_dsn)
    try:
        try:
            await conn.execute(f'CREATE DATABASE "{dbname}"')
        except asyncpg.DuplicateDatabaseError:
            pass
        except asyncpg.InsufficientPrivilegeError:
            # 无建库权限时，测试库已存在则直接使用
            try:
                probe = await asyncpg.connect(dsn, timeout=3)
            except Exception:
                raise RuntimeError(
                    f"无法创建测试库 {dbname}（缺少 CREATEDB 权限且库不存在）。"
                    "请以超级用户执行一次: ALTER USER omninav_admin CREATEDB;"
                )
            else:
                await probe.close()
    finally:
        await conn.close()

    import redis.asyncio as aioredis

    from app.core.config import get_settings

    try:
        r = aioredis.from_url(get_settings().redis_url)
        await r.ping()
        await r.aclose()
    except Exception as e:
        raise RuntimeError(f"测试 Redis 不可用: {e}") from e

    import app.models  # noqa: F401 —— 注册全部模型
    from app.core.db import Base

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session")
def prepared_db():
    """整库重建一次；Postgres/Redis 不可达时跳过依赖它的集成测试。"""
    import asyncio

    try:
        asyncio.run(_prepare_database())
    except RuntimeError as e:
        pytest.skip(str(e))
    yield


@pytest.fixture(autouse=True)
async def _close_redis_after_test():
    """security / market.cache 的 Redis 客户端是模块级单例，持有当前测试
    事件循环上的连接池；每个测试结束后在同一个 loop 内干净关闭，
    避免下个测试的 loop 已切换。"""
    yield
    from app.core import security
    from app.services.market import cache

    for mod in (security, cache):
        client = mod._redis
        mod._redis = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


def new_client():
    """每个用户一个独立 Cookie 会话的 httpx 客户端。"""
    import httpx

    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def register_user(prepared_db):
    """直接在测试库建用户，返回 user_id。"""
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models import SysUser

    async def _make(
        username: str, password: str = TEST_PASSWORD, role: str = "member"
    ) -> int:
        async with SessionLocal() as session:
            user = SysUser(
                username=username,
                password_hash=hash_password(password),
                role=role,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user.id

    return _make


@pytest.fixture
async def do_login(prepared_db):
    """在给定客户端上登录；断言成功。"""
    async def _login(client, username: str, password: str = TEST_PASSWORD) -> dict:
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _login
