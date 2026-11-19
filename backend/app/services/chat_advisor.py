"""AI 决策问答服务（多轮流式对话）。

与 advisor（三时点内参）共享上下文构建：行情 / 持仓 / 新闻材料。此处面向
用户主动提问，自由 Markdown 回答；消息落库 fact_chat_messages，每用户
一条持续会话（取最近 N 条作为多轮上下文），清空即删除全部行。
"""

import logging
from collections.abc import AsyncIterator
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import FactChatMessage, FactNewsArticle, SysUser
from app.services.advisor import (
    DISCLAIMER,
    _market_context,
    _news_material,
    _portfolio_context,
)
from app.services.llm import LlmError, chat_text_stream
from app.services.market.cache import QuoteCache

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")

# 送入 LLM 的历史消息条数上限（约 10 轮），控制上下文成本
MAX_HISTORY_MESSAGES = 20

CHAT_SYSTEM_PROMPT = f"""你是一名严谨的个人全资产组合分析师，回答用户关于投资决策的提问。硬性规则：
1. 回答必须基于随后提供的【行情数据】【用户持仓】【新闻材料】，不得编造数据或新闻；材料不足以判断时明确说明"信息不足"。
2. 涉及新闻/消息面的观点需在句末标注来源编号，如 [3]，只能引用材料中出现的编号。
3. 操作建议只给方向性、条件式参考（如"若高开超1%可考虑减持一部分"），不给出具体买卖价格点位，不做收益承诺。
4. 结合用户持仓结构回答，关注占比与集中度，而非孤立看待单一资产。
5. 用中文 Markdown 作答（可用小标题、列表、加粗），结论先行、逻辑简明；回答末尾单独一行附：{DISCLAIMER}。"""


async def build_context(
    session: AsyncSession, user_id: int, on_date: date, cache: QuoteCache
) -> str:
    """组装背景资料：最新新闻不设时间窗（取最近 N 条，避免周末空窗）。"""
    s = get_settings()
    articles = (
        (
            await session.execute(
                select(FactNewsArticle)
                .order_by(FactNewsArticle.published_at.desc())
                .limit(s.news_window_max_items)
            )
        )
        .scalars()
        .all()
    )
    news_text = _news_material(list(articles)) if articles else "（暂无新闻）"
    # slot 传 "midday" 以附带 MARKET 持仓的盘中实时涨跌（QuoteCache 缓存兜底）
    return (
        f"今天是 {on_date.isoformat()}。\n\n"
        f"【行情数据】\n{await _market_context(session, on_date)}\n\n"
        f"【用户持仓】\n"
        f"{await _portfolio_context(session, user_id, on_date, 'midday', cache)}\n\n"
        f"【新闻材料】（编号用于回答中引用来源）\n{news_text}"
    )


async def stream_answer(
    session: AsyncSession,
    user: SysUser,
    question: str,
    cache: QuoteCache,
) -> AsyncIterator[str]:
    """流式回答一次提问。

    消息序列 = system + 背景资料 + 最近历史 + 本次问题；user 消息先落库
    （失败重问不丢问题），回答流式产出，结束后落库 assistant 消息。
    LlmError 在首个增量前向调用方抛出（路由转 502）；已输出部分则追加
    中断说明并落库已有内容。
    """
    on_date = datetime.now(CST).date()
    history = (
        (
            await session.execute(
                select(FactChatMessage)
                .where(FactChatMessage.user_id == user.id)
                .order_by(FactChatMessage.id.desc())
                .limit(MAX_HISTORY_MESSAGES)
            )
        )
        .scalars()
        .all()
    )[::-1]  # 反转为 id 升序

    context = await build_context(session, user.id, on_date, cache)
    messages = (
        [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
        + [{"role": "user", "content": f"【背景资料】\n{context}"}]
        + [{"role": m.role, "content": m.content} for m in history]
        + [{"role": "user", "content": question}]
    )

    session.add(FactChatMessage(user_id=user.id, role="user", content=question))
    await session.commit()

    chunks: list[str] = []
    try:
        async for delta in chat_text_stream(messages):
            chunks.append(delta)
            yield delta
    except LlmError as exc:
        if not chunks:
            raise
        logger.warning("user=%s 问答流中断: %s", user.id, exc)
        note = f"\n\n（生成中断：{exc}）"
        chunks.append(note)
        yield note
    if chunks:
        session.add(
            FactChatMessage(user_id=user.id, role="assistant", content="".join(chunks))
        )
        await session.commit()
