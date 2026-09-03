"""复盘卡片内容生成（飞书 lark_md / Telegram Markdown 通用纯文本）。

含两类卡片：每日复盘（build_daily_card）与月度/年度复盘（build_period_card，
任务 4.5：胜率盈亏比、权益占比偏离预警、最佳/最差标的）。
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.models import FactPortfolioSnapshot
from app.services.alerts import AlertEvent
from app.services.metrics import compute_metric_summary
from app.services.nav import ZERO
from app.services.settlement import SettlementResult
from app.services.valuation import PositionValuation, PriceBook

Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")
MARKET_LABELS = {"CN": "A股", "HK": "港股", "US": "美股", "GLOBAL": "全球"}
CLASS_LABELS = {"STOCK": "股票", "ETF": "基金/ETF", "WEALTH": "银行理财", "CASH": "现金"}


def fmt_pct(x: Decimal | float | None, digits: int = 2) -> str:
    if x is None:
        return "—"
    v = Decimal(x) * 100  # 输入为小数比例（0.035 → +3.50%）
    if v == ZERO:
        return "0.00%"
    return f"{v:+.{digits}f}%"


def fmt_amount(x: Decimal | float | None, currency: str = "CNY") -> str:
    if x is None:
        return "—"
    return f"{Decimal(x):,.2f} {currency}"


def _fmt_ratio(x: Decimal | float | None, digits: int = 1) -> str:
    """占比/胜率等无符号百分比（0.75 → 75.0%）。"""
    if x is None:
        return "—"
    return f"{Decimal(x) * 100:.{digits}f}%"


def _group_share(
    valuations: list[Any], key_fn: Any, labels: dict[str, str]
) -> str:
    total = sum((v.market_value_cny for v in valuations), ZERO)
    if total == ZERO:
        return "—"
    groups: dict[str, Decimal] = {}
    for v in valuations:
        k = key_fn(v)
        groups[k] = groups.get(k, ZERO) + v.market_value_cny
    parts = [
        f"{labels.get(k, k)} {fmt_pct(g / total, 0)}"
        for k, g in sorted(groups.items(), key=lambda kv: -kv[1])
    ]
    return " | ".join(parts)


def build_daily_card(
    result: SettlementResult,
    prev_snapshot: FactPortfolioSnapshot | None,
    alerts: list[AlertEvent],
    latest_note: str | None,
    *,
    estimated: bool = False,
) -> tuple[str, list[str]]:
    """返回 (标题, 分节文本列表)。estimated=True 为 22:00 预估简报。"""
    d = result.target_date
    title = f"{'【预估值】' if estimated else ''}{d.isoformat()} 投资复盘"

    nav = result.nav
    cum_ret = (nav.unit_nav - Decimal("1")).quantize(Q4, ROUND_HALF_UP)

    def bench_pct(cur: Decimal | None, prev: Decimal | None) -> str:
        if cur is None or prev is None or prev == ZERO:
            return "—"
        return fmt_pct(cur / prev - 1)

    sections: list[str] = []

    sections.append(
        f"**单位净值 {nav.unit_nav}**（{fmt_pct(nav.daily_return)}）　"
        f"累计收益 **{fmt_pct(cum_ret)}**"
    )
    sections.append(
        f"当日盈亏 {fmt_amount(nav.daily_pnl_cny)}　"
        f"总资产 {fmt_amount(result.mv_end_of_day)}"
    )
    sections.append(
        f"基准对标：沪深300 {bench_pct(result.csi300_nav, Decimal(prev_snapshot.csi300_nav) if prev_snapshot and prev_snapshot.csi300_nav else None)}"
        f"｜标普500 {bench_pct(result.sp500_nav, Decimal(prev_snapshot.sp500_nav) if prev_snapshot and prev_snapshot.sp500_nav else None)}"
    )

    movers = sorted(
        (v for v in result.valuations if v.day_change_pct is not None),
        key=lambda v: v.day_change_pct,
    )
    if movers:
        top = movers[-1]
        bottom = movers[0]
        sections.append(
            f"领涨 {top.asset.name} {fmt_pct(top.day_change_pct)}　"
            f"领跌 {bottom.asset.name} {fmt_pct(bottom.day_change_pct)}"
        )

    sections.append(
        f"资产分布：{_group_share(result.valuations, lambda v: v.asset.market, MARKET_LABELS)}"
    )
    sections.append(
        f"大类分布：{_group_share(result.valuations, lambda v: v.asset.asset_class, CLASS_LABELS)}"
    )

    if result.net_flow_cny != ZERO:
        sections.append(f"当日外部净现金流：{fmt_amount(result.net_flow_cny)}")

    for ev in alerts:
        sections.append(f"🚨 **告警** {ev.message}")

    if latest_note:
        sections.append(f"📝 复盘笔记：{latest_note}")

    return title, sections


# ---------------------------------------------------------------------------
# 月度/年度报告（任务 4.5）
# ---------------------------------------------------------------------------

EQUITY_CLASSES = {"STOCK", "ETF"}
EQUITY_WARN_RATIO = Decimal("0.70")  # PRD §3.4：权益类占比 70% 警戒线
INF = Decimal("Infinity")


def is_last_trading_day_of_month(d: date) -> bool:
    """d 是否为本月最后一个交易日（以周一至五近似，不含节假日历）。"""
    if d.weekday() >= 5:
        return False
    nxt = d + timedelta(days=1)
    while nxt.month == d.month:
        if nxt.weekday() < 5:
            return False
        nxt += timedelta(days=1)
    return True


@dataclass(frozen=True)
class PeriodStats:
    annual: bool
    year: int
    month: int | None
    period_start: date
    period_end: date
    nav_end: Decimal | None
    period_return: Decimal | None
    total_pnl_cny: Decimal
    win_rate: Decimal | None
    profit_loss_ratio: Decimal | None  # 无亏损交易日时为 Infinity
    max_drawdown: float | None
    sharpe: float | None
    csi300_return: Decimal | None
    sp500_return: Decimal | None


def _benchmark_return(snaps: list[Any], key: str) -> Decimal | None:
    first = last = None
    for s in snaps:
        v = getattr(s, key)
        if v is None:
            continue
        v = Decimal(v)
        if first is None:
            first = v
        last = v
    if first is None or last is None or first <= ZERO:
        return None
    return (last / first - 1).quantize(Q4, ROUND_HALF_UP)


def compute_period_stats(
    *,
    annual: bool,
    year: int,
    month: int | None,
    start_snap: Any | None,
    period_snaps: list[Any],
) -> PeriodStats:
    """区间统计。start_snap 为期初基准快照（期外最后一条，可省）；
    period_snaps 为期内快照，升序。元素需有 snapshot_date/unit_nav/
    daily_return/daily_pnl_cny/csi300_nav/sp500_nav 字段。
    """
    if annual:
        period_start, period_end = date(year, 1, 1), date(year, 12, 31)
    else:
        assert month is not None
        period_start = date(year, month, 1)
        period_end = (
            date(year, month + 1, 1) - timedelta(days=1)
            if month < 12
            else date(year, 12, 31)
        )

    series = ([start_snap] if start_snap else []) + list(period_snaps)
    navs = [Decimal(s.unit_nav) for s in series]
    period_return = None
    if len(navs) >= 2 and navs[0] > ZERO:
        period_return = (navs[-1] / navs[0] - 1).quantize(Q4, ROUND_HALF_UP)

    total_pnl = sum(
        (Decimal(s.daily_pnl_cny) for s in period_snaps), ZERO
    ).quantize(Q2)

    rets = [Decimal(s.daily_return) for s in period_snaps]
    wins = [r for r in rets if r > ZERO]
    losses = [r for r in rets if r < ZERO]
    win_rate = (Decimal(len(wins)) / Decimal(len(rets))).quantize(Q4) if rets else None
    if wins and losses:
        avg_win = sum(wins, ZERO) / Decimal(len(wins))
        avg_loss = abs(sum(losses, ZERO) / Decimal(len(losses)))
        profit_loss_ratio = (avg_win / avg_loss).quantize(Q4)
    elif wins:
        profit_loss_ratio = INF  # 区间无亏损交易日
    else:
        profit_loss_ratio = None

    max_drawdown = sharpe = None
    if len(series) >= 2:
        m = compute_metric_summary(
            dates=[s.snapshot_date for s in series],
            unit_navs=[float(n) for n in navs],
            csi300_navs=[
                float(s.csi300_nav) if s.csi300_nav else None for s in series
            ],
        )
        max_drawdown = m["max_drawdown"]
        sharpe = m["sharpe"]

    return PeriodStats(
        annual=annual,
        year=year,
        month=month,
        period_start=period_start,
        period_end=period_end,
        nav_end=navs[-1] if navs else None,
        period_return=period_return,
        total_pnl_cny=total_pnl,
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        csi300_return=_benchmark_return(series, "csi300_nav"),
        sp500_return=_benchmark_return(series, "sp500_nav"),
    )


def _period_best_worst(
    valuations: list[PositionValuation], book: PriceBook, stats: PeriodStats
) -> tuple[tuple[str, Decimal] | None, tuple[str, Decimal] | None]:
    """MARKET 类持仓标的的区间涨跌幅（区间首末收盘价），返回 (最佳, 最差)。"""
    changes: list[tuple[str, Decimal]] = []
    for v in valuations:
        if v.asset.valuation_type != "MARKET":
            continue
        p0 = book.close(v.asset.asset_id, stats.period_start)
        p1 = book.close(v.asset.asset_id, stats.period_end)
        if p0 and p1 and p0 > ZERO:
            changes.append(
                (v.asset.name, (p1 / p0 - 1).quantize(Q4, ROUND_HALF_UP))
            )
    if not changes:
        return None, None
    changes.sort(key=lambda x: x[1])
    return changes[-1], changes[0]


def _fmt_plr(v: Decimal | None) -> str:
    if v is None:
        return "—"
    if v == INF:
        return "∞"
    return f"{v:.2f}"


def build_period_card(
    stats: PeriodStats,
    valuations: list[PositionValuation] | None,
    book: PriceBook | None,
) -> tuple[str, list[str]]:
    """月度/年度复盘卡片。valuations/book 缺失（行情降级）时跳过持仓明细。"""
    label = f"{stats.year}年度" if stats.annual else f"{stats.year}年{stats.month}月"
    title = f"{label} 投资复盘"

    sections: list[str] = []
    sections.append(
        f"期末单位净值 **{stats.nav_end if stats.nav_end is not None else '—'}**　"
        f"区间收益 **{fmt_pct(stats.period_return)}**　"
        f"区间盈亏 {fmt_amount(stats.total_pnl_cny)}"
    )
    sections.append(
        f"胜率 {_fmt_ratio(stats.win_rate)}　"
        f"盈亏比 {_fmt_plr(stats.profit_loss_ratio)}　"
        f"最大回撤 {fmt_pct(stats.max_drawdown)}　"
        f"夏普 {f'{stats.sharpe:.2f}' if stats.sharpe is not None else '—'}"
    )
    sections.append(
        f"基准对标：沪深300 {fmt_pct(stats.csi300_return)}｜"
        f"标普500 {fmt_pct(stats.sp500_return)}"
    )

    if valuations is not None and book is not None and valuations:
        best, worst = _period_best_worst(valuations, book, stats)
        if best and worst:
            sections.append(
                f"最佳标的 {best[0]} {fmt_pct(best[1])}　"
                f"最差标的 {worst[0]} {fmt_pct(worst[1])}"
            )

        sections.append(
            f"资产分布：{_group_share(valuations, lambda v: v.asset.asset_class, CLASS_LABELS)}"
        )
        total = sum((v.market_value_cny for v in valuations), ZERO)
        if total > ZERO:
            equity = (
                sum(
                    (
                        v.market_value_cny
                        for v in valuations
                        if v.asset.asset_class in EQUITY_CLASSES
                    ),
                    ZERO,
                )
                / total
            ).quantize(Q4)
            line = f"权益类资产（股票+ETF）占比 {_fmt_ratio(equity)}"
            if equity > EQUITY_WARN_RATIO:
                sections.append(
                    f"⚠️ {line}，超过 {_fmt_ratio(EQUITY_WARN_RATIO, 0)} 警戒线，建议再平衡"
                )
            else:
                sections.append(line)
    else:
        sections.append("期末行情/估值数据缺失，持仓明细降级")

    return title, sections
