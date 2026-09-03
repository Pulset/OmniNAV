"""量化指标服务单测：alpha/beta 回归（quantstats 0.0.81 移除后自算的路径）。"""

from datetime import date, timedelta

from app.services.metrics import compute_metric_summary

R = [0.01, -0.02, 0.03, 0.005, -0.015, 0.02]  # 组合日收益率
DATES = [date(2026, 8, 1) + timedelta(days=i) for i in range(len(R))]


def _cum(daily_returns: list[float]) -> list[float]:
    navs, v = [], 1.0
    for r in daily_returns:
        v *= 1 + r
        navs.append(v)
    return navs


def test_alpha_beta_vs_identical_benchmark():
    navs = _cum(R)
    out = compute_metric_summary(DATES, navs, navs)
    assert out["beta_vs_csi300"] is not None
    assert abs(out["beta_vs_csi300"] - 1.0) < 1e-9
    # 与基准完全同步 → 超额收益为 0
    assert out["alpha_vs_csi300"] is not None
    assert abs(out["alpha_vs_csi300"]) < 1e-9


def test_alpha_beta_double_sensitivity():
    # 基准日收益恒为组合的一半 → beta = 2,无超额
    navs = _cum(R)
    bench = _cum([r / 2 for r in R])
    out = compute_metric_summary(DATES, navs, bench)
    assert out["beta_vs_csi300"] is not None
    assert abs(out["beta_vs_csi300"] - 2.0) < 1e-9
    assert abs(out["alpha_vs_csi300"]) < 1e-9
