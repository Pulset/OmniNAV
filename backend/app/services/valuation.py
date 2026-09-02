"""估值层：PriceBook 行情簿 + 四类资产估值器（技术方案 §3.2）。

- MARKET：最近收盘价（缺价时回退加权成本并告警）
- FIXED_YIELD：按日计息，逐批次 本金 × (1 + 年化 × 持有天数/365)
- MANUAL_NAV：最近一次手动录入的单位净值（缺省回退加权成本）
- CASH：单价恒为 1
所有市值最终按即期汇率折算 CNY。
"""

import bisect
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.services.nav import ZERO
from app.services.portfolio import Lot

logger = logging.getLogger(__name__)

ONE = Decimal("1")
DAYS_PER_YEAR = Decimal("365")
Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")


class MissingPriceError(ValueError):
    pass


def fx_symbol(currency: str) -> str:
    return f"FX_{currency}CNY"


@dataclass(frozen=True)
class AssetLike:
    asset_id: str
    name: str
    asset_class: str
    market: str
    currency: str
    valuation_type: str
    expected_apr: Decimal


@dataclass
class PositionValuation:
    asset: AssetLike
    quantity: Decimal
    unit_price: Decimal  # 本币单价
    fx_rate: Decimal  # 折 CNY 汇率
    market_value_cny: Decimal
    cost_basis_cny: Decimal  # 近似：Σ(批次价×数量) × 当日汇率
    day_change_pct: Decimal | None = None  # 本币收盘价日涨跌幅（无前收盘时 None）


class PriceBook:
    """内存行情簿：(date, symbol, close) 集合，支持「不晚于某日」的最新价查询。"""

    def __init__(self, rows: Iterable[tuple[date, str, Decimal]]):
        series: dict[str, dict[date, Decimal]] = {}
        for d, symbol, close in rows:
            series.setdefault(symbol, {})[d] = close
        self._sorted: dict[str, list[date]] = {}
        self._closes: dict[str, list[Decimal]] = {}
        for symbol, m in series.items():
            dates = sorted(m)
            self._sorted[symbol] = dates
            self._closes[symbol] = [m[d] for d in dates]

    def has(self, symbol: str) -> bool:
        return symbol in self._sorted

    def close(self, symbol: str, on_or_before: date) -> Decimal | None:
        dates = self._sorted.get(symbol)
        if not dates:
            return None
        i = bisect.bisect_right(dates, on_or_before)
        if i == 0:
            return None
        return self._closes[symbol][i - 1]

    def close_with_prev(
        self, symbol: str, on_or_before: date
    ) -> tuple[Decimal | None, Decimal | None]:
        """返回 (不晚于 on_or_before 的最新收盘, 其前一交易日收盘)。"""
        dates = self._sorted.get(symbol)
        if not dates:
            return None, None
        i = bisect.bisect_right(dates, on_or_before)
        if i == 0:
            return None, None
        prev = self._closes[symbol][i - 2] if i >= 2 else None
        return self._closes[symbol][i - 1], prev

    def fx_to_cny(self, currency: str, on_or_before: date) -> Decimal:
        if currency == "CNY":
            return ONE
        rate = self.close(fx_symbol(currency), on_or_before)
        if rate is None:
            raise MissingPriceError(
                f"缺少 {currency}/CNY 汇率（不晚于 {on_or_before}），"
                "请先运行行情抓取或回补历史汇率"
            )
        return rate


def _weighted_avg_cost(lots: Sequence[Lot]) -> Decimal:
    total_cost = sum((l.price * l.quantity for l in lots), ZERO)
    total_qty = sum((l.quantity for l in lots), ZERO)
    if total_qty == ZERO:
        return ZERO
    return total_cost / total_qty


def value_asset(
    asset: AssetLike, lots: Sequence[Lot], book: PriceBook, on_date: date
) -> PositionValuation:
    """对单个资产在 on_date 估值（本币单价 → 汇率折算 → CNY 市值）。"""
    quantity = sum((l.quantity for l in lots), ZERO)
    cost_native = sum((l.price * l.quantity for l in lots), ZERO)

    vt = asset.valuation_type
    day_change: Decimal | None = None

    if vt == "CASH":
        unit_price = ONE
    elif vt == "FIXED_YIELD":
        apr = Decimal(asset.expected_apr)
        accrued = sum(
            (
                l.quantity
                * l.price
                * (ONE + apr * Decimal((on_date - l.trans_date).days) / DAYS_PER_YEAR)
                for l in lots
            ),
            ZERO,
        )
        unit_price = accrued / quantity if quantity > ZERO else ONE
    else:  # MARKET / MANUAL_NAV 均取「最近可得价格/净值」
        close, prev_close = book.close_with_prev(asset.asset_id, on_date)
        if close is None:
            close = _weighted_avg_cost(lots)
            logger.warning(
                "资产 %s 在 %s 无行情/净值数据，回退加权成本 %s",
                asset.asset_id, on_date, close,
            )
        unit_price = close
        if close is not None and prev_close not in (None, ZERO):
            day_change = (close / prev_close - 1).quantize(Q4, ROUND_HALF_UP)

    fx_rate = book.fx_to_cny(asset.currency, on_date)
    market_value = (quantity * unit_price * fx_rate).quantize(Q2, ROUND_HALF_UP)
    cost_cny = (cost_native * fx_rate).quantize(Q2, ROUND_HALF_UP)

    return PositionValuation(
        asset=asset,
        quantity=quantity,
        unit_price=unit_price,
        fx_rate=fx_rate,
        market_value_cny=market_value,
        cost_basis_cny=cost_cny,
        day_change_pct=day_change,
    )
