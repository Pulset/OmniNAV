"""统一行情适配器接口（技术方案 §2 行情接入层）。

所有 provider 为同步实现（akshare/yfinance 基于 pandas），由上层
`asyncio.to_thread` 调度，避免阻塞事件循环。
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol


class ProviderError(RuntimeError):
    pass


DailyBars = Sequence[tuple[date, Decimal]]


class MarketDataProvider(Protocol):
    def supports(self, symbol: str) -> bool: ...

    def fetch_daily(self, symbol: str, start: date, end: date) -> DailyBars: ...
