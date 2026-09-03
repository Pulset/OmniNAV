"""单位净值平滑算法 4 场景（开发计划任务 2.3 验收）。"""

from decimal import Decimal

from app.services.nav import calculate_daily_nav, settle_day

D = Decimal


def test_day0_bootstrap():
    """场景 1：初始建仓，NAV=1.0000，份额=外部现金流。"""
    nav, shares = calculate_daily_nav(D("0"), D("0"), D("100000"), D("100000"))
    assert nav == D("1.0000")
    assert shares == D("100000.0000")


def test_day0_bootstrap_no_flow_uses_market_value():
    nav, shares = calculate_daily_nav(D("0"), D("0"), D("88888"), D("0"))
    assert nav == D("1.0000")
    assert shares == D("88888.0000")


def test_pure_market_move():
    """场景 2：无出入金，净值只随市值波动。"""
    nav, shares = calculate_daily_nav(D("1.0000"), D("100000"), D("105000"), D("0"))
    assert nav == D("1.0500")
    assert shares == D("100000.0000")

    nav, shares = calculate_daily_nav(D("1.0500"), D("100000"), D("99750"), D("0"))
    assert nav == D("0.9975")
    assert shares == D("100000.0000")


def test_deposit_does_not_distort_nav():
    """场景 3：入金按当日净值增发份额，NAV 不变。

    昨日份额 100000，出入金前市值 105000（NAV=1.05），入金 21000：
    新增份额 21000/1.05 = 20000，总份额 120000；
    入金后总市值 126000，126000/120000 = 1.05 —— NAV 不变。
    """
    nav, shares = calculate_daily_nav(D("1.0000"), D("100000"), D("105000"), D("21000"))
    assert nav == D("1.0500")
    assert shares == D("120000.0000")
    assert (D("105000") + D("21000")) / shares == D("1.05")


def test_withdraw_does_not_distort_nav():
    """场景 4：出金按当日净值赎回份额，NAV 不变。"""
    nav, shares = calculate_daily_nav(D("1.0000"), D("100000"), D("95000"), D("-19000"))
    assert nav == D("0.9500")
    assert shares == D("80000.0000")
    assert (D("95000") - D("19000")) / shares == D("0.95")


def test_settle_day_returns_and_pnl():
    """settle_day：涨跌幅与当日盈亏计算。"""
    r = settle_day(
        yesterday_nav=D("1.0000"),
        yesterday_shares=D("100000"),
        yesterday_total_mv=D("100000"),
        today_mv_before_flow=D("103000"),
        today_mv_end_of_day=D("103000"),
        today_net_cash_flow=D("0"),
    )
    assert r.unit_nav == D("1.0300")
    assert r.daily_return == D("0.0300")
    assert r.daily_pnl_cny == D("3000.00")

    # 出入金日：盈亏剔除现金流
    r = settle_day(
        yesterday_nav=D("1.0000"),
        yesterday_shares=D("100000"),
        yesterday_total_mv=D("100000"),
        today_mv_before_flow=D("100000"),
        today_mv_end_of_day=D("110000"),
        today_net_cash_flow=D("10000"),
    )
    assert r.unit_nav == D("1.0000")  # 1.0 精确入金不改变净值
    assert r.daily_pnl_cny == D("0.00")
    assert r.daily_return == D("0.0000")


def test_full_liquidation_keeps_last_nav():
    """全部出金清仓：份额归零，净值沿用。"""
    nav, shares = calculate_daily_nav(D("1.2000"), D("50000"), D("60000"), D("-60000"))
    assert nav == D("1.2000")
    assert shares == D("0.0000")


def test_refund_after_liquidation_carries_nav():
    """清仓后再入金：NAV 结转昨日而非重置 1.0000，收益曲线连续。"""
    nav, shares = calculate_daily_nav(D("1.2000"), D("0"), D("0"), D("24000"))
    assert nav == D("1.2000")
    assert shares == D("20000.0000")  # 24000 / 1.2

    # 清仓后无现金流：维持空仓，NAV 仍结转
    nav, shares = calculate_daily_nav(D("1.2000"), D("0"), D("0"), D("0"))
    assert nav == D("1.2000")
    assert shares == D("0.0000")


def test_settle_day_reentry_no_phantom_return():
    """再入场日：日收益率为 0、无幽灵盈亏（旧逻辑会得到 1/1.4-1 ≈ -28.6%）。"""
    r = settle_day(
        yesterday_nav=D("1.4000"),
        yesterday_shares=D("0"),
        yesterday_total_mv=D("0"),
        today_mv_before_flow=D("0"),
        today_mv_end_of_day=D("14000"),
        today_net_cash_flow=D("14000"),
    )
    assert r.unit_nav == D("1.4000")
    assert r.daily_return == D("0.0000")
    assert r.daily_pnl_cny == D("0.00")
    assert r.total_shares == D("10000.0000")
