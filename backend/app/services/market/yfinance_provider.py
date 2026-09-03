"""yfinance 行情源：美股 / 全球 ETF / 标普500（三方免费 API）。"""

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.services.market.base import DailyBars, ProviderError

logger = logging.getLogger(__name__)

_YF_MAP = {"SP500": "^GSPC", "NASDAQ": "^IXIC"}


def _yf_symbol(symbol: str) -> str:
    if symbol in _YF_MAP:
        return _YF_MAP[symbol]
    if symbol.endswith(".US"):
        return symbol.removesuffix(".US")
    if symbol.endswith(".HK"):
        # Yahoo 港股代码不带前导零：00700.HK -> 0700.HK
        return f"{int(symbol.removesuffix('.HK'))}.HK"
    return symbol


class YFinanceProvider:
    def supports(self, symbol: str) -> bool:
        return (
            symbol.endswith(".US")
            or symbol in _YF_MAP  # SP500 / NASDAQ 指数
            or symbol.endswith(".HK")
        )

    def fetch_daily(self, symbol: str, start: date, end: date) -> DailyBars:
        import yfinance as yf

        try:
            t = yf.Ticker(_yf_symbol(symbol))
            df = t.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
            )
        except Exception as exc:
            raise ProviderError(f"yfinance 抓取 {symbol} 失败: {exc}") from exc
        if df is None or df.empty:
            return []
        bars: list[tuple[date, Decimal]] = []
        for idx, close in zip(df.index.tolist(), df["Close"].tolist(), strict=False):
            try:
                if close is None or close != close:  # NaN 缺数日跳过
                    continue
                day = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
                px = Decimal(str(close)).quantize(Decimal("0.0001"))
            except (ValueError, TypeError, InvalidOperation):
                continue
            if start <= day <= end and px > 0:
                bars.append((day, px))
        return sorted(bars)

    def fetch_realtime(self, symbol: str) -> Decimal | None:
        try:
            info = __import__("yfinance").Ticker(_yf_symbol(symbol)).fast_info
            px = Decimal(str(info["last_price"]))
            return px if px > 0 else None
        except Exception:
            logger.debug("yfinance realtime %s 失败", symbol, exc_info=True)
            return None
