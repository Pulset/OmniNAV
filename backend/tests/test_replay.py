"""已知正确答案的样例账本全量回放（开发计划 §7 回归基准）。

账本（全部 CNY）：
- Day1 (01-01): 入金 100,000 现金                        → NAV 1.0000, 份额 100,000
- Day2 (01-02): 茅台 1000股@10 (费5)，同时从现金 WITHDRAW 10,005（内部出资，流水抵消）
                收盘价 10                                  → NAV 1.0000（盈亏 -5 = 手续费）
- Day3 (01-03): 茅台涨到 11                                → NAV 1.0100（1.00995 → 四舍五入）
- Day4 (01-04): 外部入金 +10,000（按 1.00995 增发份额）      → NAV 保持 1.0100（入金不扭曲）
- Day5 (01-05): 茅台涨到 12                                → NAV 1.0190
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.nav import ZERO, settle_day
from app.services.portfolio import aggregate_holdings, net_cash_flow_cny
from app.services.valuation import AssetLike, PriceBook, value_asset

D = Decimal

CASH = AssetLike("CASH_CNY", "现金", "CASH", "CN", "CNY", "CASH", D("0"))
MT = AssetLike("600519.SH", "贵州茅台", "STOCK", "CN", "CNY", "MARKET", D("0"))
ASSETS = {CASH.asset_id: CASH, MT.asset_id: MT}

TXNS = [
    SimpleNamespace(id=1, asset_id="CASH_CNY", trans_type="DEPOSIT", trans_date=date(2026, 1, 1), price=D("1"), quantity=D("100000"), fee=D("0"), currency="CNY"),
    SimpleNamespace(id=2, asset_id="CASH_CNY", trans_type="WITHDRAW", trans_date=date(2026, 1, 2), price=D("1"), quantity=D("10005"), fee=D("0"), currency="CNY"),
    SimpleNamespace(id=3, asset_id="600519.SH", trans_type="BUY", trans_date=date(2026, 1, 2), price=D("10"), quantity=D("1000"), fee=D("5"), currency="CNY"),
    SimpleNamespace(id=4, asset_id="CASH_CNY", trans_type="DEPOSIT", trans_date=date(2026, 1, 4), price=D("1"), quantity=D("10000"), fee=D("0"), currency="CNY"),
]

PRICES = [
    (date(2026, 1, 2), "600519.SH", D("10")),
    (date(2026, 1, 3), "600519.SH", D("11")),
    (date(2026, 1, 4), "600519.SH", D("11")),
    (date(2026, 1, 5), "600519.SH", D("12")),
]


def _replay(day: date, prev_nav: Decimal, prev_shares: Decimal, prev_mv: Decimal):
    book = PriceBook(PRICES)
    today = aggregate_holdings([t for t in TXNS if t.trans_date <= day])
    before = aggregate_holdings([t for t in TXNS if t.trans_date < day])
    mv_today = sum(
        (value_asset(ASSETS[a], lots, book, day).market_value_cny for a, lots in today.items()),
        ZERO,
    )
    mv_before_flow = sum(
        (value_asset(ASSETS[a], lots, book, day).market_value_cny for a, lots in before.items()),
        ZERO,
    )
    flow = net_cash_flow_cny(
        [t for t in TXNS if t.trans_date == day],
        lambda cur, d: D("1"),
    )
    return settle_day(prev_nav, prev_shares, prev_mv, mv_before_flow, mv_today, flow)


def test_known_answer_replay():
    r1 = _replay(date(2026, 1, 1), D("0"), D("0"), D("0"))
    assert (r1.unit_nav, r1.total_shares) == (D("1.0000"), D("100000.0000"))
    assert r1.daily_pnl_cny == D("0.00")

    r2 = _replay(date(2026, 1, 2), r1.unit_nav, r1.total_shares, D("100000"))
    assert r2.unit_nav == D("1.0000")
    assert r2.total_shares == D("100000.0000")  # 内部出资流水抵消，份额不变
    assert r2.daily_pnl_cny == D("-5.00")  # 当日盈亏恰为手续费

    r3 = _replay(date(2026, 1, 3), r2.unit_nav, r2.total_shares, D("99995"))
    assert r3.unit_nav == D("1.0100")
    assert r3.total_shares == D("100000.0000")
    assert r3.daily_pnl_cny == D("1000.00")

    r4 = _replay(date(2026, 1, 4), r3.unit_nav, r3.total_shares, D("100995"))
    # 核心不变量：外部入金按当日真实净值增发份额，NAV 保持不变
    assert r4.unit_nav == r3.unit_nav == D("1.0100")
    assert r4.total_shares == D("109901.4803")  # 100000 + 10000/1.00995
    assert r4.daily_pnl_cny == D("0.00")

    r5 = _replay(date(2026, 1, 5), r4.unit_nav, r4.total_shares, D("110995"))
    assert r5.unit_nav == D("1.0190")
    assert r5.daily_pnl_cny == D("1000.00")
