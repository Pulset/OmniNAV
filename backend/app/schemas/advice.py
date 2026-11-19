from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

Slot = Literal["morning", "midday", "evening"]


class AdviceReportOut(BaseModel):
    id: int
    trade_date: date
    slot: Slot
    model: str
    prompt_version: str
    payload: dict[str, Any]
    cited_article_ids: list[int] = []
    token_usage: dict[str, Any] = {}
    created_at: datetime


class AdviceGenerateIn(BaseModel):
    slot: Slot
    trade_date: date | None = None  # 缺省为今天（补跑可指定过去交易日）


class NewsArticleOut(BaseModel):
    id: int
    source: str
    title: str
    summary: str | None = None
    url: str | None = None
    published_at: datetime
