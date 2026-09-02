"""健康检查：DB / Redis 连通性。"""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    redis_ok = False
    try:
        import redis.asyncio as aioredis

        from app.core.config import get_settings

        r = aioredis.from_url(get_settings().redis_url)
        redis_ok = bool(await r.ping())
        await r.aclose()
    except Exception:
        pass

    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "redis": redis_ok}
