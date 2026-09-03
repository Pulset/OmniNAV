"""告警引擎：单日涨跌幅（DAILY_PCT_CHANGE）与组合回撤（DRAWDOWN）。"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FactPortfolioSnapshot, SysAlertRule
from app.services.nav import ZERO
from app.services.settlement import SettlementResult
from app.services.valuation import PriceBook

logger = logging.getLogger(__name__)

Q4 = Decimal("0.0001")
ONE = Decimal("1")


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
    events: list[AlertEvent] = []
    target = result.target_date

    for rule in rules:
        threshold = Decimal(rule.threshold)
        try:
            if rule.rule_type == "DAILY_PCT_CHANGE" and rule.asset_id:
                cur, prev = book.close_with_prev(rule.asset_id, target)
                if cur and prev and prev > ZERO:
                    pct = (cur / prev - 1).quantize(Q4, ROUND_HALF_UP)
                    if abs(pct) >= threshold:
                        events.append(
                            AlertEvent(
                                rule.id,
                                rule.asset_id,
                                f"{rule.asset_id} 单日涨跌幅 {pct:+.2%}"
                                f" 触发阈值 ±{threshold:.0%}",
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
