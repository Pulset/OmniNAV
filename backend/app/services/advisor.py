"""AI 投资内参生成服务（三时点：盘前 morning / 午间 midday / 晚间 evening）。

流水线：新闻窗口查询 → 持仓/行情上下文 → LLM 结构化生成（Pydantic 校验，
失败重试一次，再失败降级为新闻标题摘要）→ 落库 fact_advice_reports →
由调用方（Job/API）推送。
"""

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    FactAdviceReport,
    FactDailyMarketData,
    SysUser,
)
from app.services.llm import LlmError, chat_json
from app.services.market.cache import QuoteCache
from app.services.market.realtime import fetch_realtime
from app.services.nav import ZERO
from app.services.news import query_news_window
from app.services.portfolio import aggregate_holdings
from app.services.settlement import (
    CSI300_SYMBOL,
    NASDAQ_SYMBOL,
    SP500_SYMBOL,
    _load_context,
)
from app.services.trade_calendar import prev_trading_day
from app.services.valuation import MissingPriceError, value_asset

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")
Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")

Slot = Literal["morning", "midday", "evening"]
SLOTS: tuple[Slot, ...] = ("morning", "midday", "evening")
SLOT_LABELS: dict[str, str] = {
    "morning": "盘前参考",
    "midday": "午间速递",
    "evening": "晚间内参",
}
# 手动触发/补跑时用该时点的名义时刻推导新闻窗口
SLOT_NOMINAL_TIME: dict[Slot, time] = {
    "morning": time(8, 45),
    "midday": time(11, 45),
    "evening": time(21, 30),
}
PROMPT_VERSION = "v1"

STANCE_LABELS = {
    "hold": "持有观望",
    "watch": "密切观察",
    "consider_add": "可考虑加仓",
    "consider_reduce": "可考虑减持",
}
DIRECTION_LABELS = {
    "positive": "利多",
    "negative": "利空",
    "neutral": "中性",
}
INDEX_LABELS = {
    CSI300_SYMBOL: "沪深300",
    SP500_SYMBOL: "标普500",
    NASDAQ_SYMBOL: "纳斯达克",
}
DISCLAIMER = "AI 生成，仅供参考，不构成投资建议"


# ---------------------------------------------------------------- 结构化输出


class HotTopic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str
    direction: Literal["positive", "negative", "neutral"] = "neutral"
    affected: list[str] = []
    reasoning: str = ""
    news_ref: list[int] = []


class PortfolioImpact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    name: str = ""
    share_pct: float | None = None
    stance: Literal["hold", "watch", "consider_add", "consider_reduce"] = "watch"
    comment: str = ""
    news_ref: list[int] = []


class AdvicePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    market_summary: str = ""
    hot_topics: list[HotTopic] = []
    portfolio_impact: list[PortfolioImpact] = []
    action_items: list[str] = []
    next_focus: str = ""
    risk_warnings: list[str] = []
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------- Prompt 模板

SYSTEM_PROMPT = f"""你是一名严谨的个人全资产组合分析师，为用户生成中文投资内参。硬性规则：
1. 只能基于【新闻材料】与【行情数据】中给出的信息作判断，不得编造数据或新闻；材料不足以判断时明确说明"信息不足"。
2. 每条观点在 news_ref 中标注来源新闻编号，只能引用材料中出现的编号。
3. 操作建议只给方向性、条件式参考（如"若高开超1%可考虑减持一部分"），不给出具体买卖价格点位，不做收益承诺。
4. 免责声明固定为："{DISCLAIMER}"。
5. 输出必须是合法 JSON（不要 markdown 围栏），Schema 如下：
{{
  "market_summary": "一句话市场总览",
  "hot_topics": [{{"topic": "主题", "direction": "positive|negative|neutral",
    "affected": ["受影响板块/资产"], "reasoning": "逻辑", "news_ref": [新闻编号]}}],
  "portfolio_impact": [{{"symbol": "资产代码", "name": "名称", "share_pct": 占比数字,
    "stance": "hold|watch|consider_add|consider_reduce", "comment": "说明", "news_ref": [新闻编号]}}],
  "action_items": ["条件式操作参考，如：若沪深300高开>1%，可考虑..."],
  "next_focus": "后续关注点",
  "risk_warnings": ["风险提示"],
  "disclaimer": "{DISCLAIMER}"
}}
字段均可为空数组/空串，宁缺毋滥。"""

SLOT_TASKS: dict[Slot, str] = {
    "morning": (
        "现在是交易日盘前（08:45，A股 09:30 开盘前）。请生成【盘前参考】：\n"
        "1. 隔夜海外市场与消息面解读\n"
        "2. 今日 A股/港股主线判断\n"
        "3. 用户持仓的盘前关注与操作参考（含高开/低开情景应对）\n"
        "4. 今日需关注的事件（财报、经济数据、政策会议等）"
    ),
    "midday": (
        "现在是交易日午间（11:45，A股午休，13:00 复牌）。请生成【午间速递】：\n"
        "1. 上午市场与用户持仓表现复盘（结合盘中行情数据）\n"
        "2. 午间新消息解读\n"
        "3. 午后关注位与 13:00 复牌前的操作参考"
    ),
    "evening": (
        "现在是交易日晚间（21:30，A股已收盘，美股临近开盘）。请生成【晚间内参】：\n"
        "1. 全天消息面与市场复盘\n"
        "2. 用户持仓的晚间/今晚美股时段操作参考\n"
        "3. 明日关注点与主线预判"
    ),
}


# ---------------------------------------------------------------- 上下文构建


async def news_window_start(slot: Slot, now: datetime) -> datetime:
    if slot == "morning":
        prev = await prev_trading_day(now.date())
        return datetime.combine(prev, time(20, 0), tzinfo=CST)
    hour = 8 if slot == "midday" else 12
    return datetime.combine(now.date(), time(hour, 0), tzinfo=CST)


def _fmt_pct(x: Decimal | None) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.2f}%"


def _news_material(articles: list) -> str:
    lines = []
    for a in reversed(articles):  # 时间正序，便于模型理解事件演进
        summary = (a.summary or "").strip()
        if summary and summary != a.title:
            summary = summary[:120]
            lines.append(f"[{a.id}] ({a.published_at:%H:%M}) {a.title}｜{summary}")
        else:
            lines.append(f"[{a.id}] ({a.published_at:%H:%M}) {a.title}")
    return "\n".join(lines)


async def _market_context(session: AsyncSession, on_date: date) -> str:
    """双基准指数最近收盘（盘前=隔夜美股+昨日A股，午/晚=当日最新可得）。"""
    lines = []
    for symbol in (CSI300_SYMBOL, SP500_SYMBOL, NASDAQ_SYMBOL):
        row = (
            await session.execute(
                select(FactDailyMarketData)
                .where(
                    FactDailyMarketData.symbol == symbol,
                    FactDailyMarketData.trade_date <= on_date,
                )
                .order_by(FactDailyMarketData.trade_date.desc())
                .limit(2)
            )
        ).scalars().all()
        if not row:
            continue
        label = INDEX_LABELS[symbol]
        close, prev = row[0].close_price, (row[1].close_price if len(row) > 1 else None)
        pct = (
            (close / prev - 1).quantize(Q4)
            if prev is not None and prev != ZERO
            else None
        )
        lines.append(f"- {label}：{row[0].trade_date} 收盘 {close}（{_fmt_pct(pct)}）")
    return "\n".join(lines) or "（暂无指数数据）"


async def _midday_realtime_pct(
    user_assets: dict, book, today: date, cache: QuoteCache
) -> dict[str, Decimal]:
    """MARKET 持仓的盘中实时涨跌（对比昨收）。失败/缺价跳过，不阻塞。"""
    out: dict[str, Decimal] = {}
    for asset_id, asset in user_assets.items():
        if asset.valuation_type != "MARKET":
            continue
        price = await cache.get_quote(asset_id)
        if price is None:
            price = await fetch_realtime(asset_id)
            if price is not None:
                await cache.set_quote(asset_id, price)
        prev = book.close(asset_id, today - timedelta(days=1))
        if price is None or prev is None or prev == ZERO:
            continue
        out[asset_id] = ((price / prev) - 1).quantize(Q4)
    return out


async def _portfolio_context(
    session: AsyncSession, user_id: int, on_date: date, slot: Slot, cache: QuoteCache
) -> str:
    """持仓快照文本：名称/数量/最新价/CNY 市值/占比（午间附盘中涨跌）。

    缺价资产跳过（估值回退批次成本仅 MARKET 缺价时发生），不抛错——
    内参不要求精确 NAV，权威净值由 22:00 简报/06:00 清算负责。
    """
    ctx = await _load_context(session, user_id, on_date)
    holdings = aggregate_holdings(ctx.txns)
    if not holdings:
        return "（用户暂无持仓记录）"

    realtime_pct: dict[str, Decimal] = {}
    if slot == "midday":
        held_assets = {aid: ctx.assets[aid] for aid in holdings if aid in ctx.assets}
        realtime_pct = await _midday_realtime_pct(
            held_assets, ctx.book, on_date, cache
        )

    lines = []
    total = ZERO
    valued: list[tuple[object, object]] = []
    for aid, lots in holdings.items():
        asset = ctx.assets.get(aid)
        if asset is None:
            continue
        try:
            v = value_asset(asset, lots, ctx.book, on_date)
        except MissingPriceError:
            continue
        total += v.market_value_cny
        valued.append((v, lots))
    for v, lots in valued:
        share = (v.market_value_cny / total).quantize(Q4) if total != ZERO else ZERO
        intraday = ""
        if v.asset.asset_id in realtime_pct:
            intraday = f"，盘中 {_fmt_pct(realtime_pct[v.asset.asset_id])}"
        qty = sum((l.quantity for l in lots), ZERO)
        lines.append(
            f"- {v.asset.name}({v.asset.asset_id}) [{v.asset.market}/"
            f"{v.asset.asset_class}] 数量 {qty.normalize()}，最新价 "
            f"{v.unit_price.normalize()} {v.asset.currency}，市值 "
            f"{v.market_value_cny.quantize(Q2).normalize()} CNY，"
            f"占比 {share * 100:.1f}%{intraday}"
        )
    header = f"组合总市值（最近可得价）：{total.quantize(Q2).normalize()} CNY"
    return "\n".join([header] + lines)


# ---------------------------------------------------------------- 生成核心


def _fallback_payload(articles: list) -> AdvicePayload:
    titles = "；".join(a.title for a in articles[:8])
    return AdvicePayload(
        market_summary=f"（模型生成失败，降级为新闻标题摘要）{titles}"
    )


def _valid_cited_ids(payload: AdvicePayload, valid_ids: set[int]) -> list[int]:
    cited: set[int] = set()
    for t in payload.hot_topics:
        cited.update(r for r in t.news_ref if r in valid_ids)
    for p in payload.portfolio_impact:
        cited.update(r for r in p.news_ref if r in valid_ids)
    return sorted(cited)


async def _call_llm(messages: list[dict]) -> tuple[AdvicePayload, dict]:
    """调用 + 校验；校验失败把错误信息回喂重试一次。"""
    last_error = ""
    for attempt in range(2):
        trial = messages if attempt == 0 else messages + [
            {"role": "user", "content": f"上次输出不合法：{last_error}，请严格按 Schema 重新输出纯 JSON。"}
        ]
        raw, usage = await chat_json(trial)
        try:
            return AdvicePayload.model_validate(raw), usage
        except ValidationError as exc:
            last_error = str(exc)[:500]
            logger.warning("内参输出校验失败（第 %s 次）: %s", attempt + 1, last_error)
    raise LlmError(f"内参输出两次校验失败: {last_error[:200]}")


async def generate_for_user(
    session: AsyncSession,
    user: SysUser,
    trade_date: date,
    slot: Slot,
    *,
    now: datetime | None = None,
    cache: QuoteCache | None = None,
) -> FactAdviceReport | None:
    """生成并落库一条内参；无新闻素材时跳过返回 None。"""
    if slot not in SLOTS:
        raise ValueError(f"未知 slot: {slot}")
    now = now or datetime.now(CST)
    cache = cache or QuoteCache()
    s = get_settings()

    start = await news_window_start(slot, now)
    articles = list(
        await query_news_window(session, start, now, limit=s.news_window_max_items)
    )
    if not articles:
        logger.info(
            "user=%s %s 无窗口内新闻（%s 起），跳过内参生成",
            user.id, slot, start,
        )
        return None

    valid_ids = {a.id for a in articles}
    user_message = (
        f"今天是 {trade_date.isoformat()}（{'周' + '一二三四五六日'[trade_date.weekday()]}）。\n\n"
        f"【任务】\n{SLOT_TASKS[slot]}\n\n"
        f"【行情数据】\n{await _market_context(session, trade_date)}\n\n"
        f"【用户持仓】\n{await _portfolio_context(session, user.id, trade_date, slot, cache)}\n\n"
        f"【新闻材料】（编号用于 news_ref 引用）\n{_news_material(articles)}"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    try:
        payload, usage = await _call_llm(messages)
    except LlmError:
        logger.exception("user=%s %s LLM 生成失败，降级为新闻摘要", user.id, slot)
        payload = _fallback_payload(articles)
        usage = {}

    cited = _valid_cited_ids(payload, valid_ids)
    values = {
        "user_id": user.id,
        "trade_date": trade_date,
        "slot": slot,
        "model": s.llm_model or "unconfigured",
        "prompt_version": PROMPT_VERSION,
        "payload": payload.model_dump(),
        "cited_article_ids": cited,
        "token_usage": usage,
    }
    stmt = pg_insert(FactAdviceReport).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_advice_user_date_slot",
        set_={
            "model": stmt.excluded.model,
            "prompt_version": stmt.excluded.prompt_version,
            "payload": stmt.excluded.payload,
            "cited_article_ids": stmt.excluded.cited_article_ids,
            "token_usage": stmt.excluded.token_usage,
            "created_at": func.now(),
        },
    )
    await session.execute(stmt)
    await session.commit()
    # 回读持久化行（id/created_at 由库生成，upsert 构造的临时对象不含）
    saved = (
        await session.execute(
            select(FactAdviceReport).where(
                FactAdviceReport.user_id == user.id,
                FactAdviceReport.trade_date == trade_date,
                FactAdviceReport.slot == slot,
            )
        )
    ).scalar_one()
    return saved


# ---------------------------------------------------------------- 推送卡片


def build_advice_card(
    trade_date: date, slot: Slot, payload: AdvicePayload
) -> tuple[str, list[str]]:
    title = f"{trade_date.isoformat()} 【{SLOT_LABELS[slot]}】AI 投资内参"
    sections: list[str] = []

    if payload.market_summary:
        sections.append(f"📰 市场总览\n{payload.market_summary}")

    if payload.hot_topics:
        lines = []
        for t in payload.hot_topics:
            ref = f"（来源 {'#' + ','.join(map(str, t.news_ref))}）" if t.news_ref else ""
            affected = f"，影响：{'、'.join(t.affected)}" if t.affected else ""
            lines.append(
                f"- **{t.topic}**（{DIRECTION_LABELS.get(t.direction, t.direction)}{affected}）{ref}\n"
                f"  {t.reasoning}"
            )
        sections.append("🔥 热点解读\n" + "\n".join(lines))

    if payload.portfolio_impact:
        lines = []
        for p in payload.portfolio_impact:
            ref = f"（来源 {'#' + ','.join(map(str, p.news_ref))}）" if p.news_ref else ""
            share = f"（占比 {p.share_pct:.1f}%）" if p.share_pct is not None else ""
            lines.append(
                f"- {p.name or p.symbol}{share} → {STANCE_LABELS.get(p.stance, p.stance)}{ref}\n"
                f"  {p.comment}"
            )
        sections.append("💼 持仓影响\n" + "\n".join(lines))

    if payload.action_items:
        sections.append("🎯 操作参考\n" + "\n".join(f"- {i}" for i in payload.action_items))

    if payload.next_focus:
        sections.append(f"⏭ 后续关注\n{payload.next_focus}")

    if payload.risk_warnings:
        sections.append("⚠️ 风险提示\n" + "\n".join(f"- {w}" for w in payload.risk_warnings))

    sections.append(DISCLAIMER)
    return title, sections
