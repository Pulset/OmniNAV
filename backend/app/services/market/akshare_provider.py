"""AkShare 行情源：A股/港股日收盘 + 沪深300 指数（三方免费 API）。

列名做防御式解析（兼容东财/新浪两种返回格式），接口变动时抛 ProviderError
而非静默返回错误数据。
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.services.market.base import DailyBars, ProviderError

logger = logging.getLogger(__name__)

_DATE_COLS = ("日期", "date", "trade_date", "日期 ")
_CLOSE_COLS = ("收盘", "close", "收盘价", "Close")


def _pick_column(df, candidates: tuple[str, ...]):
    lower = {str(c).strip().lower(): c for c in df.columns}
    for name in candidates:
        if name in df.columns:
            return df[name]
        if name.lower() in lower:
            return df[lower[name.lower()]]
    return None


def _to_bars(df, start: date, end: date) -> list[tuple[date, Decimal]]:
    date_col = _pick_column(df, _DATE_COLS)
    close_col = _pick_column(df, _CLOSE_COLS)
    if date_col is None or close_col is None:
        raise ProviderError(
            f"AkShare 返回列无法识别: {list(df.columns)}，可能接口已变更"
        )
    bars: list[tuple[date, Decimal]] = []
    for d, c in zip(date_col.tolist(), close_col.tolist(), strict=False):
        try:
            if isinstance(d, str):
                d = d.strip()[:10].replace("/", "-")
                day = date.fromisoformat(d)
            else:
                day = d.date() if hasattr(d, "date") else date.fromisoformat(str(d))
            close = Decimal(str(c)).quantize(Decimal("0.0001"))
        except (ValueError, TypeError, InvalidOperation):
            continue
        if start <= day <= end and close > 0:
            bars.append((day, close))
    return sorted(bars)


class AkshareProvider:
    """覆盖：600519.SH / 000001.SZ（A股）、00700.HK（港股）、CSI300（沪深300）。"""

    def supports(self, symbol: str) -> bool:
        return symbol.endswith((".SH", ".SZ", ".HK")) or symbol == "CSI300"

    def fetch_daily(self, symbol: str, start: date, end: date) -> DailyBars:
        import akshare as ak

        try:
            if symbol == "CSI300":
                df = ak.index_zh_a_hist(
                    symbol="000300",
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
            elif symbol.endswith(".HK"):
                code = symbol.removesuffix(".HK")
                df = ak.stock_hk_daily(symbol=code, adjust="")
            else:
                code = symbol.split(".")[0]
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="",
                )
        except Exception as exc:  # akshare 内部抛的类型不稳定，统一收口
            raise ProviderError(f"AkShare 抓取 {symbol} 失败: {exc}") from exc
        return _to_bars(df, start, end)


def yesterday_bounds(end: date) -> tuple[date, date]:
    """给单日抓取留出前溯窗口，便于拿到「最近可得」收盘。"""
    return end - timedelta(days=10), end
