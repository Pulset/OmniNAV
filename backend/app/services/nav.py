"""基金份额法单位净值（Unit NAV）平滑核算引擎。

纯函数、无 IO，Decimal 全程精度（技术方案 §3.1）。
出入金按当日真实净值增发/赎回份额，保证 NAV 走势只反映市场波动与投资收益。
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")
ZERO = Decimal("0")
INITIAL_NAV = Decimal("1.0000")


@dataclass(frozen=True)
class NavResult:
    unit_nav: Decimal
    total_shares: Decimal
    daily_return: Decimal
    daily_pnl_cny: Decimal


def calculate_daily_nav(
    yesterday_nav: Decimal,
    yesterday_shares: Decimal,
    today_market_value_before_flow: Decimal,
    today_net_cash_flow: Decimal,
) -> tuple[Decimal, Decimal]:
    """计算当日单位净值与新总份额。

    - yesterday_shares 为 0 且 yesterday_nav 为 0 视为初始建仓日（Day 0）：
      NAV = 1.0000，份额 = 当日外部现金流（无现金流则取当日市值）。
    - yesterday_shares 为 0 但 yesterday_nav > 0 是「清仓后再入场」：
      净值结转昨日（保证全生命周期 NAV 曲线连续、只反映投资收益），
      份额按该净值折算当日现金流；当日无现金流则维持空仓。
    - today_market_value_before_flow 是「昨日持仓 × 今日价格」的总市值，
      即出入金发生前因市场波动产生的真实净值分子。
    """
    if yesterday_shares == ZERO:
        if yesterday_nav > ZERO:
            # 清仓后再入场：NAV 结转，避免重置 1.0000 造成收益曲线断裂
            if today_net_cash_flow == ZERO:
                return (
                    yesterday_nav.quantize(Q4, rounding=ROUND_HALF_UP),
                    ZERO.quantize(Q4, rounding=ROUND_HALF_UP),
                )
            shares = (today_net_cash_flow / yesterday_nav).quantize(
                Q4, rounding=ROUND_HALF_UP
            )
            return yesterday_nav.quantize(Q4, rounding=ROUND_HALF_UP), shares
        base = (
            today_net_cash_flow
            if today_net_cash_flow != ZERO
            else today_market_value_before_flow
        )
        return INITIAL_NAV, base.quantize(Q4, rounding=ROUND_HALF_UP)

    if today_market_value_before_flow == ZERO:
        # 组合已清空：净值沿用昨日，份额归零
        return (
            yesterday_nav.quantize(Q4, rounding=ROUND_HALF_UP),
            ZERO.quantize(Q4, rounding=ROUND_HALF_UP),
        )

    today_nav = today_market_value_before_flow / yesterday_shares
    delta_shares = today_net_cash_flow / today_nav
    today_shares = yesterday_shares + delta_shares
    return (
        today_nav.quantize(Q4, rounding=ROUND_HALF_UP),
        today_shares.quantize(Q4, rounding=ROUND_HALF_UP),
    )


def settle_day(
    yesterday_nav: Decimal,
    yesterday_shares: Decimal,
    yesterday_total_mv: Decimal,
    today_mv_before_flow: Decimal,
    today_mv_end_of_day: Decimal,
    today_net_cash_flow: Decimal,
) -> NavResult:
    """单日完整清算：净值/份额 + 当日涨跌幅 + 当日盈亏。

    当日盈亏 = 今日终局市值 - 昨日终局市值 - 今日外部净现金流
    （Day 0 时昨日市值记 0，公式同样成立）。
    """
    unit_nav, total_shares = calculate_daily_nav(
        yesterday_nav, yesterday_shares, today_mv_before_flow, today_net_cash_flow
    )
    if yesterday_nav > ZERO:
        daily_return = (unit_nav / yesterday_nav - 1).quantize(
            Q4, rounding=ROUND_HALF_UP
        )
    else:
        daily_return = ZERO.quantize(Q4, rounding=ROUND_HALF_UP)
    daily_pnl = (
        today_mv_end_of_day - yesterday_total_mv - today_net_cash_flow
    ).quantize(Q2, rounding=ROUND_HALF_UP)
    return NavResult(
        unit_nav=unit_nav,
        total_shares=total_shares,
        daily_return=daily_return,
        daily_pnl_cny=daily_pnl,
    )
