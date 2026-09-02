"""量化指标服务：基于 QuantStats 计算夏普、最大回撤、波动率、对标 Alpha/Beta。

输入为按日期升序的快照序列（含 unit_nav 与归一化基准净值）。
"""

import logging
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)


def compute_metric_summary(
    dates: Sequence[Any],
    unit_navs: Sequence[float],
    csi300_navs: Sequence[float | None],
) -> dict[str, float | None]:
    out: dict[str, float | None] = {
        "cumulative_return": None,
        "cagr": None,
        "sharpe": None,
        "max_drawdown": None,
        "volatility": None,
        "win_rate": None,
        "alpha_vs_csi300": None,
        "beta_vs_csi300": None,
        "days": len(unit_navs),
    }
    if len(unit_navs) < 2 or unit_navs[0] <= 0:
        return out

    import pandas as pd

    index = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    nav = pd.Series(unit_navs, index=index, dtype="float64").sort_index()
    returns = nav.pct_change().dropna()
    if returns.empty:
        return out

    out["cumulative_return"] = float(nav.iloc[-1] / nav.iloc[0] - 1)
    out["win_rate"] = float((returns > 0).mean())

    try:
        import quantstats as qs

        out["cagr"] = _f(qs.stats.cagr(returns))
        out["sharpe"] = _f(qs.stats.sharpe(returns))
        out["max_drawdown"] = _f(qs.stats.max_drawdown(returns))
        out["volatility"] = _f(qs.stats.volatility(returns))

        bench = pd.Series(csi300_navs, index=index, dtype="float64").sort_index()
        bench = bench.dropna()
        if len(bench) >= 2 and bench.iloc[0] > 0:
            bench_ret = bench.pct_change().dropna()
            common = returns.index.intersection(bench_ret.index)
            if len(common) >= 5:
                r, b = returns.loc[common], bench_ret.loc[common]
                out["alpha_vs_csi300"] = _f(qs.stats.alpha(r, b))
                out["beta_vs_csi300"] = _f(qs.stats.beta(r, b))
    except Exception:
        logger.warning("QuantStats 指标计算失败", exc_info=True)
    return out


def _f(x: Any) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
        return v if v == v else None  # NaN guard
    except (TypeError, ValueError):
        return None
