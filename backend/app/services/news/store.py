"""新闻入库与窗口查询：url_hash 幂等 upsert + slot 时间窗筛选。"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FactNewsArticle
from app.services.news.akshare_news import fetch_all_news
from app.services.news.base import NewsItem, fingerprint

logger = logging.getLogger(__name__)

# 发布时间早于该天数的旧闻不落库（财经早餐接口带数百条历史回填）
_MAX_AGE_DAYS = 45


async def upsert_news(session: AsyncSession, items: list[NewsItem]) -> int:
    """按指纹幂等写入，返回新插入条数。"""
    now = datetime.now()
    stale_floor = (now - timedelta(days=_MAX_AGE_DAYS)).date()
    rows = []
    seen: set[str] = set()
    for item in items:
        fp = fingerprint(item)
        # 按日期粒度比较，兼容 naive（provider）/ aware（测试）时间
        if fp in seen or item.published_at.date() < stale_floor:
            continue
        seen.add(fp)
        rows.append(
            {
                "source": item.source,
                "title": item.title[:512],
                "summary": item.summary,
                "url": item.url,
                "url_hash": fp,
                # AkShare 返回北京时间的 naive datetime，统一补 CST 时区
                "published_at": item.published_at.astimezone()
                if item.published_at.tzinfo is None
                else item.published_at,
            }
        )
    if not rows:
        return 0
    stmt = pg_insert(FactNewsArticle).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["url_hash"])
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


async def fetch_and_store_news(session: AsyncSession) -> int:
    """抓取全部新闻源并幂等入库（to_thread 包装同步 AkShare）。"""
    items = await asyncio.to_thread(fetch_all_news)
    inserted = await upsert_news(session, items)
    logger.info("新闻抓取完成: 共 %s 条，新入库 %s 条", len(items), inserted)
    return inserted


async def query_news_window(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    limit: int = 60,
) -> list[FactNewsArticle]:
    """取 [start, end] 窗口内最新 limit 条（published_at 倒序）。"""
    return (
        (
            await session.execute(
                select(FactNewsArticle)
                .where(
                    FactNewsArticle.published_at >= start,
                    FactNewsArticle.published_at <= end,
                )
                .order_by(FactNewsArticle.published_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
