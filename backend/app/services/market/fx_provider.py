"""汇率源：Frankfurter（欧洲央行参考汇率，免费无 Key）。

返回 USD/CNY、HKD/CNY 日度序列，写入行情表符号 FX_USDCNY / FX_HKDCNY。
周末/节假日无报价，由 PriceBook 的「最近可得」逻辑自动回退。
"""

import logging
from datetime import date
from decimal import Decimal

import httpx

from app.services.market.base import ProviderError
from app.services.valuation import fx_symbol

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.frankfurter.app"
_CURRENCIES = ("USD", "HKD")


class FrankfurterFxProvider:
    async def fetch_range(self, start: date, end: date) -> list[tuple[date, str, Decimal]]:
        rows: list[tuple[date, str, Decimal]] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for currency in _CURRENCIES:
                try:
                    resp = await client.get(
                        f"{_BASE_URL}/{start.isoformat()}..{end.isoformat()}",
                        params={"from": currency, "to": "CNY"},
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                except Exception as exc:
                    raise ProviderError(
                        f"Frankfurter 汇率抓取 {currency}/CNY 失败: {exc}"
                    ) from exc
                for day_str, rates in payload.get("rates", {}).items():
                    cny = rates.get("CNY")
                    if cny:
                        rows.append(
                            (date.fromisoformat(day_str), fx_symbol(currency), Decimal(str(cny)))
                        )
        return rows
