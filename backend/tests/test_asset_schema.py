"""AssetCreate 裸代码自动补交易所后缀（录入约定：行情路由按后缀识别标的）。"""

import pytest
from pydantic import ValidationError

from app.core.enums import AssetClass, Market, ValuationType
from app.schemas.asset import AssetCreate


def _make(asset_id, market, vt=ValuationType.MARKET, cls=AssetClass.ETF):
    return AssetCreate(
        asset_id=asset_id,
        name="测试资产",
        asset_class=cls,
        market=market,
        currency="CNY",
        valuation_type=vt,
        expected_apr=0,
    )


def test_cn_etf_bare_code_gets_sh():
    assert _make("510310", Market.CN).asset_id == "510310.SH"


def test_cn_sse_stock_gets_sh():
    assert _make("600519", Market.CN, cls=AssetClass.STOCK).asset_id == "600519.SH"


def test_cn_sz_stock_and_chinext_get_sz():
    assert _make("000001", Market.CN, cls=AssetClass.STOCK).asset_id == "000001.SZ"
    assert _make("300750", Market.CN, cls=AssetClass.STOCK).asset_id == "300750.SZ"


def test_suffix_case_normalized():
    assert _make("510310.sh", Market.CN).asset_id == "510310.SH"


def test_hk_code_padded_to_five_digits():
    assert _make("700", Market.HK, cls=AssetClass.STOCK).asset_id == "00700.HK"
    assert _make("00700", Market.HK, cls=AssetClass.STOCK).asset_id == "00700.HK"


def test_us_ticker_uppercased():
    assert _make("tsla", Market.US, cls=AssetClass.STOCK).asset_id == "TSLA.US"


def test_already_suffixed_untouched():
    assert _make("TSLA.US", Market.US, cls=AssetClass.STOCK).asset_id == "TSLA.US"
    assert _make("00700.HK", Market.HK, cls=AssetClass.STOCK).asset_id == "00700.HK"


def test_non_market_ids_untouched():
    cash = _make("CASH_CNY", Market.CN, vt=ValuationType.CASH, cls=AssetClass.CASH)
    assert cash.asset_id == "CASH_CNY"
    wealth = _make("CMB_WEALTH_01", Market.CN, vt=ValuationType.MANUAL_NAV,
                   cls=AssetClass.WEALTH)
    assert wealth.asset_id == "CMB_WEALTH_01"


def test_unrecognizable_market_code_rejected():
    with pytest.raises(ValidationError):
        _make("ABC123", Market.CN)  # 非 6 位纯数字且无后缀
    with pytest.raises(ValidationError):
        _make("830799", Market.CN)  # 北交所代码段，行情路由暂不支持


def test_whitespace_stripped_before_normalizing():
    assert _make(" 510310 ", Market.CN).asset_id == "510310.SH"
