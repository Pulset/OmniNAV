"""A股交易日历（AkShare tool_trade_date_hist_sina，spike 验证可用）。

进程内缓存当日有效；接口失败时退化为「周一至周五」判断（宁可多生成
也不漏生成），退化情况记录 warning。
"""

import asyncio
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_dates: frozenset[date] | None = None
_fetched_on: date | None = None
_lock = asyncio.Lock()


async def _ensure_calendar(today: date) -> None:
    global _dates, _fetched_on
    if _dates is not None and _fetched_on == today:
        return
    async with _lock:
        if _dates is not None and _fetched_on == today:
            return

        def _fetch() -> frozenset[date]:
            import akshare as ak

            df = ak.tool_trade_date_hist_sina()
            return frozenset(df["trade_date"].tolist())

        try:
            _dates = await asyncio.to_thread(_fetch)
            _fetched_on = today
            logger.info("交易日历已加载: %s 个交易日", len(_dates))
        except Exception:
            logger.exception("交易日历加载失败，退化为周一至周五判断")


def _fallback(d: date) -> bool:
    return d.weekday() < 5


async def is_trading_day(d: date) -> bool:
    await _ensure_calendar(date.today())
    if _dates is None:
        return _fallback(d)
    return d in _dates


async def prev_trading_day(d: date) -> date:
    """d 之前（不含 d）最近的一个交易日。"""
    await _ensure_calendar(date.today())
    cursor = d - timedelta(days=1)
    for _ in range(30):
        if _dates is not None:
            if cursor in _dates:
                return cursor
        elif _fallback(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return d - timedelta(days=1)
