"""Redis 缓存：盘中行情 TTL 缓存 + 告警去重锁（防外部 API 限流与刷屏）。"""

import logging
from decimal import Decimal

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class QuoteCache:
    def __init__(self, url: str | None = None, ttl: int | None = None):
        settings = get_settings()
        self.ttl = ttl or settings.quote_cache_ttl_seconds
        self._redis = aioredis.from_url(
            url or settings.redis_url, decode_responses=True
        )

    async def get_quote(self, symbol: str) -> Decimal | None:
        try:
            raw = await self._redis.get(f"quote:{symbol}")
            return Decimal(raw) if raw else None
        except Exception:
            logger.debug("Redis 不可用，跳过缓存读取", exc_info=True)
            return None

    async def set_quote(self, symbol: str, price: Decimal) -> None:
        try:
            await self._redis.set(f"quote:{symbol}", str(price), ex=self.ttl)
        except Exception:
            logger.debug("Redis 不可用，跳过缓存写入", exc_info=True)

    async def try_lock(self, key: str, ttl_seconds: int = 43200) -> bool:
        """SET NX EX：同一告警 12 小时内只推一次。"""
        try:
            return bool(await self._redis.set(f"lock:{key}", "1", ex=ttl_seconds, nx=True))
        except Exception:
            return True  # Redis 不可用时放行，宁可重复推送也不漏推
