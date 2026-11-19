"""AI 内参 API 集成测试：鉴权、查询、新闻列表、手动生成（mock LLM）。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import new_client, register_user, do_login  # noqa: F401

CST = ZoneInfo("Asia/Shanghai")


def _uid() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


async def test_advice_endpoints_require_auth(prepared_db):
    async with new_client() as client:
        for method, path in [
            ("GET", "/api/advice/latest?slot=morning"),
            ("GET", "/api/advice?days=7"),
            ("POST", "/api/advice/generate"),
            ("GET", "/api/advice/news"),
        ]:
            resp = await client.request(method, path)
            assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


async def test_latest_and_history_empty(prepared_db, register_user, do_login):  # noqa: F811
    name = f"adv_{_uid()}"
    await register_user(name)
    async with new_client() as client:
        await do_login(client, name)
        assert (await client.get("/api/advice/latest?slot=morning")).json() is None
        assert (await client.get("/api/advice?days=7")).json() == []


async def test_generate_requires_llm_config(prepared_db, register_user, do_login):  # noqa: F811
    name = f"adv_{_uid()}"
    await register_user(name)
    async with new_client() as client:
        await do_login(client, name)
        resp = await client.post(
            "/api/advice/generate", json={"slot": "morning"}
        )
        assert resp.status_code == 503


async def test_generate_and_query_roundtrip(
    prepared_db, register_user, do_login, monkeypatch
):  # noqa: F811
    from app.core.db import SessionLocal
    from app.services.news import upsert_news
    from app.services.news.base import NewsItem

    # 1) 种子新闻：当前时刻附近，保证落在任意 slot 窗口内
    now = datetime.now(CST)
    items = [
        NewsItem(
            source="em_global",
            title=f"[api测试] 生成内参新闻 {i}",
            summary=None,
            url=f"http://api-test/{_uid()}/{i}",
            published_at=now - timedelta(minutes=i + 1),
        )
        for i in range(3)
    ]
    async with SessionLocal() as session:
        await upsert_news(session, items)

    # 2) mock LLM：跳过网络，返回固定合法 JSON
    import app.services.advisor as advisor

    async def _fake_chat(messages):
        return (
            {
                "market_summary": "测试总览",
                "hot_topics": [
                    {"topic": "测试主题", "direction": "positive",
                     "affected": ["A股"], "reasoning": "r", "news_ref": [1]}
                ],
                "portfolio_impact": [],
                "action_items": ["若高开可观望"],
                "next_focus": "今晚数据",
                "risk_warnings": [],
                "disclaimer": "AI 生成，仅供参考，不构成投资建议",
            },
            {"total_tokens": 42},
        )

    monkeypatch.setattr(advisor, "chat_json", _fake_chat)
    import app.api.routes.advice as route

    monkeypatch.setattr(route, "llm_configured", lambda: True)

    name = f"adv_{_uid()}"
    await register_user(name)
    async with new_client() as client:
        await do_login(client, name)
        # 新闻列表可见
        news = (await client.get("/api/advice/news")).json()
        assert any("[api测试]" in n["title"] for n in news)
        # 手动生成 → 201，payload 回读一致
        resp = await client.post(
            "/api/advice/generate", json={"slot": "evening"}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["payload"]["market_summary"] == "测试总览"
        assert body["token_usage"]["total_tokens"] == 42
        # latest / history 可查
        latest = (
            await client.get("/api/advice/latest?slot=evening")
        ).json()
        assert latest["id"] == body["id"]
        history = (await client.get("/api/advice?days=1")).json()
        assert any(r["id"] == body["id"] for r in history)
