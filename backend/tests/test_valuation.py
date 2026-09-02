"""四类估值器与 PriceBook（开发计划任务 2.2 验收）。"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.portfolio import Lot
from app.services.valuation import (
    AssetLike,
    MissingPriceError,
    PriceBook,
    value_asset,
)

D = Decimal


def asset(**kw):
    base = dict(
        asset_id="600519.SH",
        name="贵州茅台",
        asset_class="STOCK",
        market="CN",
        currency="CNY",
        valuation_type="MARKET",
        expected_apr=D("0"),
    )
    base.update(kw)
    return AssetLike(**base)


def book(rows):
    return PriceBook(rows)


def test_pricebook_latest_on_or_before():
    b = book([
        (date(2026, 1, 1), "X", D("10")),
        (date(2026, 1, 2), "X", D("11")),
        (date(2026, 1, 5), "X", D("12")),
    ])
    assert b.close("X", date(2026, 1, 3)) == D("11")
    assert b.close("X", date(2026, 1, 1)) == D("10")
    assert b.close("X", date(2025, 12, 31)) is None
    assert b.close("X", date(2026, 6, 1)) == D("12")  # 周末/停牌回退最近价


def test_fx_to_cny_missing_raises():
    b = book([])
    with pytest.raises(MissingPriceError):
        b.fx_to_cny("USD", date(2026, 1, 1))


def test_valuate_market_with_fx():
    a = asset(asset_id="AAPL.US", currency="USD", market="US")
    b = book([
        (date(2026, 1, 1), "AAPL.US", D("100")),
        (date(2026, 1, 2), "AAPL.US", D("102")),
        (date(2026, 1, 1), "FX_USDCNY", D("7.1")),
    ])
    v = value_asset(a, [Lot(date(2026, 1, 1), D("100"), D("10"))], b, date(2026, 1, 2))
    assert v.unit_price == D("102")
    assert v.market_value_cny == D("7242.00")  # 10 × 102 × 7.1
    assert v.day_change_pct == D("0.0200")


def test_valuate_market_fallback_to_cost():
    a = asset()
    v = value_asset(a, [Lot(date(2026, 1, 1), D("1500"), D("10"))], book([]), date(2026, 1, 2))
    assert v.unit_price == D("1500")  # 无行情回退加权成本
    assert v.day_change_pct is None


def test_valuate_fixed_yield_daily_accrual():
    """固收按日计息：本金 10000，年化 2.8%，持有 365 天 → 10280。"""
    a = asset(
        asset_id="CMB_WEALTH_01",
        name="招行定期",
        asset_class="WEALTH",
        valuation_type="FIXED_YIELD",
        expected_apr=D("0.028"),
    )
    v = value_asset(
        a, [Lot(date(2026, 1, 1), D("1"), D("10000"))], book([]), date(2027, 1, 1)
    )
    assert v.unit_price == D("1.0280")
    assert v.market_value_cny == D("10280.00")


def test_valuate_manual_nav():
    a = asset(valuation_type="MANUAL_NAV", asset_class="WEALTH", asset_id="BANK_NAV_01")
    b = book([(date(2026, 1, 3), "BANK_NAV_01", D("1.0321"))])
    v = value_asset(a, [Lot(date(2026, 1, 1), D("1"), D("20000"))], b, date(2026, 1, 4))
    assert v.unit_price == D("1.0321")
    assert v.market_value_cny == D("20642.00")


def test_valuate_cash():
    a = asset(
        asset_id="CASH_CNY", asset_class="CASH", valuation_type="CASH"
    )
    v = value_asset(a, [Lot(date(2026, 1, 1), D("1"), D("52000.5"))], book([]), date(2026, 1, 2))
    assert v.unit_price == D("1")
    assert v.market_value_cny == D("52000.50")


def test_valuate_hkd_cash_with_fx():
    a = asset(
        asset_id="CASH_HKD", asset_class="CASH", valuation_type="CASH", currency="HKD"
    )
    b = book([(date(2026, 1, 1), "FX_HKDCNY", D("0.92"))])
    v = value_asset(a, [Lot(date(2026, 1, 1), D("1"), D("1000"))], b, date(2026, 1, 2))
    assert v.market_value_cny == D("920.00")
