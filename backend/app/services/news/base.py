"""新闻适配器统一接口（对齐 services/market/base.py 的 Provider 协议模式）。

provider 为同步实现（基于 AkShare/pandas），由上层 `asyncio.to_thread`
调度，避免阻塞事件循环。
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol


@dataclass(frozen=True)
class NewsItem:
    source: str
    title: str
    summary: str | None
    url: str | None
    published_at: datetime


class NewsProvider(Protocol):
    name: str

    def fetch(self) -> list[NewsItem]: ...


def fingerprint(item: NewsItem) -> str:
    """去重指纹：有 URL 用 URL；无 URL 源（财联社电报）退化为 标题+源+日期。

    同标题同日跨源不合并——保留多源视角，交给 LLM 在摘要阶段合并同类事件。
    """
    if item.url:
        raw = item.url.strip()
    else:
        raw = f"{item.source}|{item.title.strip()}|{item.published_at:%Y%m%d}"
    return sha256(raw.encode("utf-8")).hexdigest()
