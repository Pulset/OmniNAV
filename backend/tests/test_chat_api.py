"""AI 问答 API 集成测试：鉴权、多轮流式回答（mock LLM）、守卫、清空。"""

import uuid

import pytest

from tests.conftest import new_client, register_user, do_login  # noqa: F401


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _fake_stream(parts, captured):
    """构造 mock chat_text_stream：记录入参 messages，逐段产出 parts。"""

    async def _fake(messages):
        captured.append(messages)
        for p in parts:
            yield p

    return _fake


async def test_chat_endpoints_require_auth(prepared_db):
    async with new_client() as client:
        for method, path in [
            ("GET", "/api/chat/messages"),
            ("POST", "/api/chat/ask"),
            ("DELETE", "/api/chat/messages"),
        ]:
            resp = await client.request(method, path)
            assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


async def test_ask_requires_llm_config(
    prepared_db, register_user, do_login, monkeypatch
):  # noqa: F811
    import app.api.routes.chat as route

    # 本机 .env 可能已配置 LLM，显式关闭以测守卫
    monkeypatch.setattr(route, "llm_configured", lambda: False)
    name = f"chat_{_uid()}"
    await register_user(name)
    async with new_client() as client:
        await do_login(client, name)
        resp = await client.post("/api/chat/ask", json={"question": "测试"})
        assert resp.status_code == 503


async def test_ask_validation(prepared_db, register_user, do_login):  # noqa: F811
    name = f"chat_{_uid()}"
    await register_user(name)
    async with new_client() as client:
        await do_login(client, name)
        resp = await client.post("/api/chat/ask", json={"question": ""})
        assert resp.status_code == 422


async def test_ask_locked_returns_429(
    prepared_db, register_user, do_login, monkeypatch
):  # noqa: F811
    import app.api.routes.chat as route
    from app.services.market.cache import QuoteCache

    monkeypatch.setattr(route, "llm_configured", lambda: True)

    name = f"chat_{_uid()}"
    uid = await register_user(name)
    lock_key = f"chat-ask:{uid}"
    cache = QuoteCache()
    await cache.release_lock(lock_key)  # 清理上次运行残留锁（user id 跨轮重复）
    try:
        assert await cache.try_lock(lock_key, ttl_seconds=120)
        async with new_client() as client:
            await do_login(client, name)
            resp = await client.post("/api/chat/ask", json={"question": "测试"})
            assert resp.status_code == 429
    finally:
        await cache.release_lock(lock_key)


async def test_ask_llm_error_returns_502(
    prepared_db, register_user, do_login, monkeypatch
):  # noqa: F811
    import app.api.routes.chat as route
    import app.services.chat_advisor as service
    from app.services.llm import LlmError
    from app.services.market.cache import QuoteCache

    monkeypatch.setattr(route, "llm_configured", lambda: True)
    captured: list = []

    async def _boom(messages):
        captured.append(messages)
        raise LlmError("连接失败")
        yield  # noqa: unreachable — 使其成为 async generator，对齐真实签名

    monkeypatch.setattr(service, "chat_text_stream", _boom)

    name = f"chat_{_uid()}"
    uid = await register_user(name)
    await QuoteCache().release_lock(f"chat-ask:{uid}")
    async with new_client() as client:
        await do_login(client, name)
        resp = await client.post("/api/chat/ask", json={"question": "测试"})
        assert resp.status_code == 502
        # 问题已落库（失败重问不丢）
        msgs = (await client.get("/api/chat/messages")).json()
        assert [m["role"] for m in msgs] == ["user"]
        assert msgs[0]["content"] == "测试"


async def test_ask_stream_and_multiturn(
    prepared_db, register_user, do_login, monkeypatch
):  # noqa: F811
    import app.api.routes.chat as route
    import app.services.chat_advisor as service
    from app.services.market.cache import QuoteCache

    monkeypatch.setattr(route, "llm_configured", lambda: True)

    name = f"chat_{_uid()}"
    uid = await register_user(name)
    await QuoteCache().release_lock(f"chat-ask:{uid}")  # 清理残留
    async with new_client() as client:
        await do_login(client, name)

        # 第 1 问：流式返回拼接结果
        captured: list = []
        monkeypatch.setattr(
            service, "chat_text_stream", _fake_stream(["部分", "回答"], captured)
        )
        resp = await client.post("/api/chat/ask", json={"question": "问题一"})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/plain")
        assert resp.text == "部分回答"

        msgs = (await client.get("/api/chat/messages")).json()
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "问题一"),
            ("assistant", "部分回答"),
        ]

        # 第 2 问：LLM 收到 system + 背景资料 + 历史两轮 + 新问题
        monkeypatch.setattr(
            service, "chat_text_stream", _fake_stream(["答案二"], captured)
        )
        resp = await client.post("/api/chat/ask", json={"question": "问题二"})
        assert resp.status_code == 200
        assert resp.text == "答案二"

        assert len(captured) == 2
        roles = [m["role"] for m in captured[1]]
        assert roles == ["system", "user", "user", "assistant", "user"]
        assert captured[1][2]["content"] == "问题一"
        assert captured[1][3]["content"] == "部分回答"
        assert captured[1][4]["content"] == "问题二"
        assert "【背景资料】" in captured[1][1]["content"]

        msgs = (await client.get("/api/chat/messages")).json()
        assert len(msgs) == 4
        assert msgs[3]["content"] == "答案二"

        # 清空
        resp = await client.delete("/api/chat/messages")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": 4}
        assert (await client.get("/api/chat/messages")).json() == []


async def test_ask_stream_interrupt_persists_partial(
    prepared_db, register_user, do_login, monkeypatch
):  # noqa: F811
    """首块后 LLM 失败：已输出内容 + 中断说明落库。"""
    import app.api.routes.chat as route
    import app.services.chat_advisor as service
    from app.services.llm import LlmError
    from app.services.market.cache import QuoteCache

    monkeypatch.setattr(route, "llm_configured", lambda: True)
    captured: list = []

    async def _partial_then_fail(messages):
        captured.append(messages)
        yield "前半段"
        raise LlmError("流断开")

    monkeypatch.setattr(service, "chat_text_stream", _partial_then_fail)

    name = f"chat_{_uid()}"
    uid = await register_user(name)
    await QuoteCache().release_lock(f"chat-ask:{uid}")  # 清理残留
    async with new_client() as client:
        await do_login(client, name)
        resp = await client.post("/api/chat/ask", json={"question": "问题"})
        assert resp.status_code == 200
        assert resp.text.startswith("前半段")
        assert "生成中断" in resp.text

        msgs = (await client.get("/api/chat/messages")).json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[1]["content"].startswith("前半段")
