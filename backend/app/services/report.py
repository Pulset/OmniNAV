"""复盘卡片内容生成（飞书 lark_md / Telegram Markdown 通用纯文本）。"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.models import FactPortfolioSnapshot
from app.services.alerts import AlertEvent
from app.services.nav import ZERO
from app.services.settlement import SettlementResult

Q4 = Decimal("0.0001")
MARKET_LABELS = {"CN": "A股", "HK": "港股", "US": "美股", "GLOBAL": "全球"}
CLASS_LABELS = {"STOCK": "股票", "ETF": "基金/ETF", "WEALTH": "银行理财", "CASH": "现金"}


def fmt_pct(x: Decimal | float | None, digits: int = 2) -> str:
    if x is None:
        return "—"
    v = Decimal(x)
    if v == ZERO:
        return "0.00%"
    return f"{v:+.{digits}f}%"


def fmt_amount(x: Decimal | float | None, currency: str = "CNY") -> str:
    if x is None:
        return "—"
    return f"{Decimal(x):,.2f} {currency}"


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
