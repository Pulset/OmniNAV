"""AI 决策问答入口：多轮消息查询、流式提问、清空会话。"""

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.jobs.news_advisor import llm_configured
from app.models import FactChatMessage, SysUser
from app.schemas import ChatAskIn, ChatMessageOut
from app.services.llm import LlmError
from app.services.market.cache import QuoteCache

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat", tags=["chat"], dependencies=[Depends(get_current_user)]
)


@router.get("/messages", response_model=list[ChatMessageOut])
async def chat_messages(
    limit: int = Query(default=200, ge=1, le=500),
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """当前用户全部消息（id 升序）。"""
    return (
        (
            await session.execute(
                select(FactChatMessage)
                .where(FactChatMessage.user_id == user.id)
                .order_by(FactChatMessage.id.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


@router.post("/ask")
async def ask(
    payload: ChatAskIn,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """流式提问：text/plain 分块返回回答增量（前端逐段拼接）。"""
    from app.services.chat_advisor import stream_answer

    if not llm_configured():
        raise HTTPException(
            503, "LLM 未配置（backend/.env 设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）"
        )
    cache = QuoteCache()
    if not await cache.try_lock(f"chat-ask:{user.id}", ttl_seconds=120):
        raise HTTPException(429, "上一条回答仍在生成中，请稍候")
    try:
        gen = stream_answer(session, user, payload.question, cache)
        # 先拉首块：配置/连接类错误在这里以 HTTP 状态码暴露（流开始后无法改状态）
        try:
            first = await gen.__anext__()
        except StopAsyncIteration:
            first = None
        except LlmError as exc:
            raise HTTPException(502, f"LLM 生成失败: {exc}") from exc
    except BaseException:
        # 流开始前的任何失败都释放锁，避免用户被 429 到锁自然过期
        await cache.release_lock(f"chat-ask:{user.id}")
        raise

    async def body(
        first: str | None, gen: AsyncIterator[str]
    ) -> AsyncIterator[str]:
        try:
            if first:
                yield first
            async for delta in gen:
                yield delta
        finally:
            await cache.release_lock(f"chat-ask:{user.id}")

    return StreamingResponse(
        body(first, gen),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/messages")
async def clear_messages(
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """清空当前用户会话。"""
    result = await session.execute(
        delete(FactChatMessage).where(FactChatMessage.user_id == user.id)
    )
    await session.commit()
    return {"deleted": result.rowcount}
