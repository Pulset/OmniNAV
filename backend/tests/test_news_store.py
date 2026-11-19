"""新闻入库/窗口查询集成测试（依赖本地 Postgres/Redis，不可达自动跳过）。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import FactNewsArticle
from app.services.news import query_news_window, upsert_news
from app.services.news.base import NewsItem

CST = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=CST)


def _item(tag: str, i: int, *, published: datetime | None = None):
    return NewsItem(
        source="em_global",
        title=f"[{tag}] 测试新闻 {i}",
        summary=f"摘要 {i}",
        url=f"http://test/{tag}/{i}",
        published_at=published or NOW - timedelta(minutes=i),
    )


async def _count(session, tag: str) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(FactNewsArticle).where(
                FactNewsArticle.title.like(f"[{tag}]%")
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_upsert_idempotent(prepared_db):
    items = [_item("idem", i) for i in range(5)]
    async with SessionLocal() as session:
        first = await upsert_news(session, items)
        again = await upsert_news(session, items)
        rows = await _count(session, "idem")
    assert first == 5
    assert again == 0
    assert rows == 5


@pytest.mark.asyncio
async def test_upsert_skips_stale_articles(prepared_db):
    stale = _item("stale", 0, published=NOW - timedelta(days=60))
    fresh = _item("stale", 1)
    async with SessionLocal() as session:
        inserted = await upsert_news(session, [stale, fresh])
        rows = await _count(session, "stale")
    assert inserted == 1
    assert rows == 1


@pytest.mark.asyncio
async def test_query_window_filters_by_time(prepared_db):
    old = _item("win", 1, published=NOW - timedelta(hours=10))
    recent = _item("win", 2, published=NOW - timedelta(minutes=5))
    async with SessionLocal() as session:
        await upsert_news(session, [old, recent])
        got = await query_news_window(
            session, NOW - timedelta(hours=1), NOW, limit=10
        )
    titles = [a.title for a in got]
    assert recent.title in titles
    assert old.title not in titles
