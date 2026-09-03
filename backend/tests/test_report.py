"""月度/年度报告单元测试（任务 4.5）：

最后交易日判定、区间统计（胜率/盈亏比/区间收益）、权益占比偏离预警、
最佳/最差标的。
"""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.services.report import (
    PeriodStats,
    build_period_card,
    compute_period_stats,
    is_last_trading_day_of_month,
)
from app.services.valuation import AssetLike, PositionValuation, PriceBook


def _snap(d, nav, ret, pnl, csi=None, spx=None):
    return SimpleNamespace(
        snapshot_date=d,
        unit_nav=D(nav),
        daily_return=D(ret),
        daily_pnl_cny=D(pnl),
        csi300_nav=D(csi) if csi is not None else None,
        sp500_nav=D(spx) if spx is not None else None,
    )


def test_is_last_trading_day_of_month():
    assert is_last_trading_day_of_month(date(2026, 9, 30))  # 周三，月末
    assert not is_last_trading_day_of_month(date(2026, 9, 29))
    assert not is_last_trading_day_of_month(date(2026, 9, 26))  # 周六
    # 2026-02-28 是周六 → 最后交易日为 02-27 周五
    assert is_last_trading_day_of_month(date(2026, 2, 27))
    assert not is_last_trading_day_of_month(date(2026, 2, 28))
    # 2026-10-31 是周六 → 最后交易日为 10-30 周五
    assert is_last_trading_day_of_month(date(2026, 10, 30))
    assert not is_last_trading_day_of_month(date(2026, 10, 31))


def test_compute_period_stats():
    start = _snap(date(2026, 7, 31), "1.0000", "0.0050", "50", csi="1000", spx="5000")
    period = [
        _snap(date(2026, 8, 3), "1.0100", "0.0100", "100", csi="1005", spx="5010"),
        _snap(date(2026, 8, 4), "0.9900", "-0.0198", "-200", csi="1000", spx="4990"),
        _snap(date(2026, 8, 5), "1.0000", "0.0101", "100", csi="1005", spx="5000"),
        _snap(date(2026, 8, 6), "1.0200", "0.0200", "200", csi="1010", spx="5020"),
    ]
    stats = compute_period_stats(
        annual=False, year=2026, month=8, start_snap=start, period_snaps=period
    )
    assert (stats.period_start, stats.period_end) == (
        date(2026, 8, 1),
        date(2026, 8, 31),
    )
    assert stats.nav_end == D("1.0200")
    assert stats.period_return == D("0.0200")  # 1.02 / 1.00 - 1
    assert stats.total_pnl_cny == D("200.00")  # 期初快照的盈亏不计入
    assert stats.win_rate == D("0.75")  # 3 盈 / 4 个交易日
    # 盈亏比 = 平均盈利 0.0401/3 / 平均亏损 0.0198 ≈ 0.6751
    assert stats.profit_loss_ratio == D("0.6751")
    assert stats.max_drawdown is not None and stats.max_drawdown < 0
    assert stats.csi300_return == D("0.0100")  # 1010 / 1000 - 1
    assert stats.sp500_return == D("0.0040")  # 5020 / 5000 - 1


def test_compute_period_stats_no_start_snap():
    period = [
        _snap(date(2026, 8, 3), "1.0000", "0.0000", "0"),
        _snap(date(2026, 8, 4), "1.0500", "0.0500", "500"),
    ]
    stats = compute_period_stats(
        annual=False, year=2026, month=8, start_snap=None, period_snaps=period
    )
    assert stats.period_return == D("0.0500")
    assert stats.win_rate == D("0.50")


def test_compute_period_stats_all_wins():
    period = [
        _snap(date(2026, 8, 3), "1.0100", "0.0100", "100"),
        _snap(date(2026, 8, 4), "1.0200", "0.0099", "100"),
    ]
    stats = compute_period_stats(
        annual=False, year=2026, month=8, start_snap=None, period_snaps=period
    )
    assert stats.win_rate == D("1.0000")
    assert stats.profit_loss_ratio is not None
    assert stats.profit_loss_ratio == D("Infinity")


def _pv(asset_id, name, cls, mv, vt="MARKET"):
    asset = AssetLike(asset_id, name, cls, "CN", "CNY", vt, D("0"))
    return PositionValuation(
        asset=asset,
        quantity=D("1"),
        unit_price=mv,
        fx_rate=D("1"),
        market_value_cny=mv,
        cost_basis_cny=mv,
    )


_PRICES = [
    (date(2026, 8, 1), "600519.SH", D("10")),
    (date(2026, 8, 31), "600519.SH", D("12")),  # +20%
    (date(2026, 8, 1), "NVDA", D("10")),
    (date(2026, 8, 31), "NVDA", D("9")),  # -10%
]


def _august_stats() -> PeriodStats:
    return PeriodStats(
        annual=False,
        year=2026,
        month=8,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        nav_end=D("1.0200"),
        period_return=D("0.0200"),
        total_pnl_cny=D("200.00"),
        win_rate=D("0.75"),
        profit_loss_ratio=None,
        max_drawdown=None,
        sharpe=None,
        csi300_return=D("0.0100"),
        sp500_return=D("0.0040"),
    )


def test_build_period_card_best_worst_and_equity_alert():
    # 权益（股票+ETF）占比 90%：茅台 80 / NVDA 10 / 现金 10 → 触发 70% 警戒线
    valuations = [
        _pv("600519.SH", "贵州茅台", "STOCK", D("80")),
        _pv("NVDA", "英伟达", "STOCK", D("10")),
        _pv("CASH_CNY", "现金", "CASH", D("10"), vt="CASH"),
    ]
    title, sections = build_period_card(_august_stats(), valuations, PriceBook(_PRICES))

    assert title == "2026年8月 投资复盘"
    text = "\n".join(sections)
    assert "最佳标的 贵州茅台 +20.00%" in text
    assert "最差标的 英伟达 -10.00%" in text
    assert "⚠️" in text and "90.0%" in text  # 权益占比偏离预警
    assert "现金 +10%" in text  # 资产分布


def test_build_period_card_equity_below_threshold():
    valuations = [
        _pv("600519.SH", "贵州茅台", "STOCK", D("40")),
        _pv("CASH_CNY", "现金", "CASH", D("60"), vt="CASH"),
    ]
    _, sections = build_period_card(_august_stats(), valuations, PriceBook(_PRICES))
    text = "\n".join(sections)
    assert "⚠️" not in text
    assert "权益类资产（股票+ETF）占比 40.0%" in text


def test_build_period_card_annual_and_degraded():
    stats = PeriodStats(
        annual=True,
        year=2026,
        month=None,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        nav_end=None,
        period_return=None,
        total_pnl_cny=D("0.00"),
        win_rate=None,
        profit_loss_ratio=None,
        max_drawdown=None,
        sharpe=None,
        csi300_return=None,
        sp500_return=None,
    )
    title, sections = build_period_card(stats, None, None)
    assert title == "2026年度 投资复盘"
    assert "降级" in "\n".join(sections)
