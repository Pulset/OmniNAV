"""告警引擎：单日涨跌幅（±/涨/跌）与组合回撤（DRAWDOWN）。"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DAILY_RULE_TYPES, RuleType
from app.models import DimAsset, FactPortfolioSnapshot, SysAlertRule
from app.services.nav import ZERO
from app.services.settlement import SettlementResult
from app.services.valuation import PriceBook, manual_nav_symbol

logger = logging.getLogger(__name__)

Q4 = Decimal("0.0001")
ONE = Decimal("1")


def daily_hit(rule_type: str, pct: Decimal, threshold: Decimal) -> bool:
    """单日涨跌幅类规则的方向判断：GAIN 看 ≥t，LOSS 看 ≤−t，PCT_CHANGE 看 |·|≥t。"""
    if rule_type == RuleType.DAILY_GAIN:
        return pct >= threshold
    if rule_type == RuleType.DAILY_LOSS:
        return pct <= -threshold
    return abs(pct) >= threshold


@dataclass(frozen=True)
class AlertEvent:
    rule_id: int
    asset_id: str | None
    message: str


async def evaluate_eod_alerts(
    session: AsyncSession, user_id: int, book: PriceBook, result: SettlementResult
) -> list[AlertEvent]:
    """终局清算后按该用户的 sys_alert_rules 评估告警事件。"""
    rules = (
        (
            await session.execute(
                select(SysAlertRule).where(
                    SysAlertRule.user_id == user_id,
                    SysAlertRule.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    val_types = {
        aid: vt
        for aid, vt in (
            await session.execute(
                select(DimAsset.asset_id, DimAsset.valuation_type).where(
                    DimAsset.user_id == user_id
                )
            )
        ).all()
    }
    events: list[AlertEvent] = []
    target = result.target_date

    for rule in rules:
        threshold = Decimal(rule.threshold)
        try:
            if rule.rule_type in DAILY_RULE_TYPES and rule.asset_id:
                symbol = (
                    manual_nav_symbol(rule.asset_id)
                    if val_types.get(rule.asset_id) == "MANUAL_NAV"
                    else rule.asset_id
                )
                cur, prev = book.close_with_prev(symbol, target)
                if cur and prev and prev > ZERO:
                    pct = (cur / prev - 1).quantize(Q4, ROUND_HALF_UP)
                    if daily_hit(rule.rule_type, pct, threshold):
                        label = {
                            RuleType.DAILY_GAIN: f"涨幅阈值 {threshold:.0%}",
                            RuleType.DAILY_LOSS: f"跌幅阈值 {threshold:.0%}",
                        }.get(rule.rule_type, f"阈值 ±{threshold:.0%}")
                        events.append(
                            AlertEvent(
                                rule.id,
                                rule.asset_id,
                                f"{rule.asset_id} 单日涨跌幅 {pct:+.2%} 触发{label}",
                            )
                        )
            elif rule.rule_type == "DRAWDOWN":
                max_nav = (
                    await session.execute(
                        select(func.max(FactPortfolioSnapshot.unit_nav)).where(
                            FactPortfolioSnapshot.user_id == user_id,
                            FactPortfolioSnapshot.snapshot_date <= target,
                        )
                    )
                ).scalar()
                if max_nav and Decimal(max_nav) > ZERO:
                    dd = (
                        ONE - Decimal(result.nav.unit_nav) / Decimal(max_nav)
                    ).quantize(Q4, ROUND_HALF_UP)
                    if dd >= threshold:
                        events.append(
                            AlertEvent(
                                rule.id,
                                None,
                                f"组合自历史高点回撤 {dd:.2%} 触发阈值 {threshold:.0%}",
                            )
                        )
        except Exception:
            logger.exception("评估告警规则 %s 失败", rule.id)
    return events
