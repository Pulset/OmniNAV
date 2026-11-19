"""AI 内参单元测试：LLM JSON 解析、payload 校验、引用过滤、窗口与卡片。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.services.advisor import (
    AdvicePayload,
    HotTopic,
    PortfolioImpact,
    SLOT_LABELS,
    _valid_cited_ids,
    build_advice_card,
    news_window_start,
)
from app.services.llm.client import LlmError, extract_json
from app.services.news.base import NewsItem, fingerprint

CST = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------- extract_json


def test_extract_json_bare():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_embedded_in_prose():
    text = '好的，以下是结果：\n{"market_summary": "总览", "hot_topics": []}\n希望有帮助'
    assert extract_json(text) == {"market_summary": "总览", "hot_topics": []}


def test_extract_json_nested_braces():
    assert extract_json('x {"a": {"b": 2}} y') == {"a": {"b": 2}}


def test_extract_json_garbage_raises():
    with pytest.raises(LlmError):
        extract_json("这不是 JSON")


# ---------------------------------------------------------------- payload


def test_payload_defaults_minimal():
    p = AdvicePayload(market_summary="总览")
    assert p.hot_topics == []
    assert "不构成投资建议" in p.disclaimer


def test_payload_rejects_bad_direction():
    with pytest.raises(ValidationError):
        HotTopic(topic="x", direction="bullish")


def test_payload_rejects_bad_stance():
    with pytest.raises(ValidationError):
        PortfolioImpact(symbol="x", stance="all_in")


# ---------------------------------------------------------------- 引用过滤


def test_valid_cited_ids_filters_hallucination():
    payload = AdvicePayload(
        market_summary="s",
        hot_topics=[HotTopic(topic="t", news_ref=[1, 99])],
        portfolio_impact=[PortfolioImpact(symbol="a", news_ref=[2])],
    )
    assert _valid_cited_ids(payload, {1, 2, 3}) == [1, 2]


# ---------------------------------------------------------------- 新闻窗口


@pytest.mark.asyncio
async def test_news_window_start_morning_uses_prev_trading_day(monkeypatch):
    import app.services.advisor as adv

    # 周一 08:45 → 上一交易日为上周五 20:00（覆盖周末消息）
    async def _fake_prev(d):
        return date(2026, 10, 23)

    monkeypatch.setattr(adv, "prev_trading_day", _fake_prev)
    now = datetime(2026, 10, 26, 8, 45, tzinfo=CST)  # 周一
    assert await news_window_start("morning", now) == datetime(
        2026, 10, 23, 20, 0, tzinfo=CST
    )


@pytest.mark.asyncio
async def test_news_window_start_midday_evening():
    now = datetime(2026, 10, 27, 11, 45, tzinfo=CST)
    assert await news_window_start("midday", now) == datetime(
        2026, 10, 27, 8, 0, tzinfo=CST
    )
    assert await news_window_start("evening", now) == datetime(
        2026, 10, 27, 12, 0, tzinfo=CST
    )


# ---------------------------------------------------------------- 交易日历退化


@pytest.mark.asyncio
async def test_trade_calendar_fallback_to_weekday(monkeypatch):
    from app.services import trade_calendar as tc

    async def _noop(_today):
        return None  # 模拟「日历不可用」：加载失败后 _dates 仍为 None

    monkeypatch.setattr(tc, "_ensure_calendar", _noop)
    monkeypatch.setattr(tc, "_dates", None)
    assert await tc.is_trading_day(date(2026, 10, 26))  # 周一
    assert not await tc.is_trading_day(date(2026, 10, 31))  # 周六


# ---------------------------------------------------------------- 指纹去重


def _item(title: str, url: str | None = None) -> NewsItem:
    return NewsItem(
        source="cls_telegraph",
        title=title,
        summary=None,
        url=url,
        published_at=datetime(2026, 10, 26, 10, 0),
    )


def test_fingerprint_url_dedup():
    assert fingerprint(_item("标题A", url="http://x/1")) == fingerprint(
        _item("标题变了", url="http://x/1")
    )


def test_fingerprint_title_fallback():
    a = fingerprint(_item("同一标题"))
    b = fingerprint(_item("同一标题"))
    c = fingerprint(_item("不同标题"))
    assert a == b and a != c


# ---------------------------------------------------------------- 推送卡片


def test_build_advice_card_structure():
    payload = AdvicePayload(
        market_summary="总览文本",
        hot_topics=[
            HotTopic(
                topic="美联储降息预期",
                direction="positive",
                affected=["黄金", "美股"],
                reasoning="材料显示……",
                news_ref=[1],
            )
        ],
        portfolio_impact=[
            PortfolioImpact(
                symbol="600519",
                name="贵州茅台",
                share_pct=12.3,
                stance="consider_reduce",
                comment="……",
            )
        ],
        action_items=["若高开>1% 可考虑减持一部分"],
        next_focus="今晚美国CPI",
        risk_warnings=["消息面变化快"],
    )
    title, sections = build_advice_card(date(2026, 10, 26), "morning", payload)
    assert "【盘前参考】" in title
    joined = "\n".join(sections)
    assert "利多" in joined
    assert "可考虑减持" in joined  # stance 中文标签
    assert "不构成投资建议" in joined
    assert SLOT_LABELS["morning"] == "盘前参考"
