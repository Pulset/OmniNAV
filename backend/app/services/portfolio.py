"""持仓聚合与组合级外部现金流计算（纯函数）。

交易语义（与 PRD §3.2 及设计决策 D3/D4 一致）：
- BUY/SELL 只改变目标资产数量；资金侧不自动记账。
- BUY 视为外部资金流入组合（+成本含费），SELL 视为资金流出（-净回款），
  保证以外部资金直接买入时不扭曲 NAV。
- 若购买资金来自组合内已跟踪的现金资产（如朝朝宝），同时记录一笔该现金的
  WITHDRAW 即可——两笔外部现金流金额抵消，NAV 不受影响。
- DIVIDEND 是组合内部收益，落到 CASH 资产上，不产生外部现金流。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.core.enums import FLOW_SIGN
from app.services.nav import ZERO

Q2 = Decimal("0.01")


@dataclass
class Lot:
    trans_date: date
    price: Decimal
    quantity: Decimal


class OverSellError(ValueError):
    pass


class TxnLike(Protocol):
    asset_id: str
    trans_type: str
    trans_date: date
    price: Decimal
    quantity: Decimal
    fee: Decimal


def aggregate_holdings(txns: Sequence[TxnLike]) -> dict[str, list[Lot]]:
    """按交易日期顺序重放出每个资产的持仓批次（FIFO）。超卖抛 OverSellError。"""
    ordered = sorted(
        txns, key=lambda t: (t.trans_date, getattr(t, "id", 0) or 0)
    )
    holdings: dict[str, list[Lot]] = {}
    for t in ordered:
        tt = str(t.trans_type)
        lots = holdings.setdefault(t.asset_id, [])
        if tt in ("BUY", "DEPOSIT", "DIVIDEND"):
            lots.append(Lot(t.trans_date, t.price, t.quantity))
        elif tt in ("SELL", "WITHDRAW"):
            remaining = t.quantity
            while remaining > ZERO and lots:
                take = min(lots[0].quantity, remaining)
                lots[0].quantity -= take
                remaining -= take
                if lots[0].quantity == ZERO:
                    lots.pop(0)
            if remaining > ZERO:
                raise OverSellError(
                    f"{t.asset_id} 在 {t.trans_date} 的 {tt} 数量超过持仓"
                )
        else:
            raise ValueError(f"未知交易类型: {tt}")
    return {aid: lots for aid, lots in holdings.items() if lots}


def aggregate_diluted_cost(txns: Sequence[TxnLike]) -> dict[str, Decimal]:
    """摊薄持仓成本（券商 App 口径，含手续费），返回 asset_id -> 本币成本。

    - BUY/DEPOSIT：成本 += 金额 + 手续费
    - SELL/WITHDRAW：成本 -= 净回款（金额 - 手续费）
    - DIVIDEND：仅增加数量（分红是收益，不增加成本）
    - 清仓（数量归零）时成本结转归零，从零重计
    """
    ordered = sorted(txns, key=lambda t: (t.trans_date, getattr(t, "id", 0) or 0))
    cost: dict[str, Decimal] = {}
    qty: dict[str, Decimal] = {}
    for t in ordered:
        aid = t.asset_id
        tt = str(t.trans_type)
        amount = t.price * t.quantity
        fee = t.fee or ZERO
        if tt in ("BUY", "DEPOSIT"):
            cost[aid] = cost.get(aid, ZERO) + amount + fee
            qty[aid] = qty.get(aid, ZERO) + t.quantity
        elif tt in ("SELL", "WITHDRAW"):
            cost[aid] = cost.get(aid, ZERO) - (amount - fee)
            qty[aid] = qty.get(aid, ZERO) - t.quantity
        elif tt == "DIVIDEND":
            qty[aid] = qty.get(aid, ZERO) + t.quantity
        else:
            raise ValueError(f"未知交易类型: {tt}")
        if qty[aid] == ZERO:
            cost[aid] = ZERO
        elif qty[aid] < ZERO:
            raise OverSellError(f"{aid} 在 {t.trans_date} 的 {tt} 数量超过持仓")
    return {aid: c for aid, c in cost.items() if qty.get(aid, ZERO) > ZERO}


def net_cash_flow_cny(
    txns: Sequence[TxnLike],
    fx_rate: Callable[[str, date], Decimal],
) -> Decimal:
    """计算一组交易折算 CNY 后的组合级外部净现金流（入金/买入为正）。"""
    total = ZERO
    for t in txns:
        sign = FLOW_SIGN[str(t.trans_type)]
        if sign == 0:
            continue
        amount = t.price * t.quantity
        if t.fee and t.fee > ZERO:
            amount = amount + t.fee if str(t.trans_type) == "BUY" else amount - t.fee
        total += sign * amount * fx_rate(t.currency, t.trans_date)
    return total.quantize(Q2)
