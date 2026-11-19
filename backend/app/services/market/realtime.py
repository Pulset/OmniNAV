"""实时价获取：A股走 AkShare 买卖五档快照，港股/美股走 yfinance。

盘中监控（intraday_monitor）与 AI 内参午间上下文（advisor）共用。
"""

import asyncio
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


async def fetch_realtime(symbol: str) -> Decimal | None:
    if symbol.endswith((".SH", ".SZ")):
        def _ak():
            import akshare as ak

            code = symbol.split(".")[0]
            df = ak.stock_bid_ask_em(symbol=code)
            row = df[df["item"] == "最新"]
            if not row.empty:
                return Decimal(str(row.iloc[0]["value"]))
            return None

        try:
            return await asyncio.to_thread(_ak)
        except Exception:
            logger.debug("AkShare 实时 %s 失败", symbol, exc_info=True)
            return None

    from app.services.market.yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    return await asyncio.to_thread(provider.fetch_realtime, symbol)
