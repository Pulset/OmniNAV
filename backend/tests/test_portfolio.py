"""持仓重放（FIFO）与组合级外部现金流计算（开发计划任务 2.1 验收）。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.portfolio import (
    OverSellError,
    aggregate_diluted_cost,
    aggregate_holdings,
    net_cash_flow_cny,
)

D = Decimal


def txn(**kw):
    base = dict(
        asset_id="600519.SH",
        trans_type="BUY",
        trans_date=date(2026, 1, 1),
        price=D("10"),
        quantity=D("100"),
        fee=D("0"),
        currency="CNY",
        id=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_holdings_replay_buy_sell():
    txns = [
        txn(trans_date=date(2026, 1, 1), price=D("10"), quantity=D("100")),
        txn(trans_date=date(2026, 1, 5), price=D("12"), quantity=D("50")),
        txn(trans_date=date(2026, 2, 1), trans_type="SELL", price=D("11"), quantity=D("80")),
    ]
    holdings = aggregate_holdings(txns)
    lots = holdings["600519.SH"]
    # FIFO: 卖 80 先消耗第一批 100 中的 80，剩 20@10 + 50@12
    assert [ (l.price, l.quantity) for l in lots ] == [(D("10"), D("20")), (D("12"), D("50"))]


def test_holdings_oversell_raises():
    txns = [
        txn(quantity=D("10")),
        txn(trans_date=date(2026, 1, 2), trans_type="SELL", quantity=D("15")),
    ]
    with pytest.raises(OverSellError):
        aggregate_holdings(txns)


def test_holdings_empty_after_full_sell():
    txns = [txn(quantity=D("10")), txn(trans_date=date(2026, 1, 2), trans_type="SELL", quantity=D("10"))]
    assert aggregate_holdings(txns) == {}


def test_net_cash_flow_signs_and_fees():
    """BUY +成本含费 / SELL -净回款 / DEPOSIT + / WITHDRAW - / DIVIDEND 0，汇率折算。"""
    fx = lambda cur, d: D("7") if cur == "USD" else D("1")
    txns = [
        txn(trans_type="DEPOSIT", asset_id="CASH_CNY", price=D("1"), quantity=D("100000")),
        txn(trans_type="WITHDRAW", asset_id="CASH_CNY", trans_date=date(2026, 1, 2), price=D("1"), quantity=D("5000")),
        txn(trans_type="BUY", asset_id="AAPL.US", trans_date=date(2026, 1, 3), price=D("100"), quantity=D("10"), fee=D("1"), currency="USD"),
        txn(trans_type="SELL", asset_id="AAPL.US", trans_date=date(2026, 1, 4), price=D("110"), quantity=D("4"), fee=D("1"), currency="USD"),
        txn(trans_type="DIVIDEND", asset_id="CASH_USD", trans_date=date(2026, 1, 5), price=D("1"), quantity=D("50"), currency="USD"),
    ]
    flow = net_cash_flow_cny(txns, fx)
    # +100000 - 5000 + (100*10+1)*7 - (110*4-1)*7 + 0
    assert flow == D("100000") - D("5000") + D("1001") * 7 - D("439") * 7


def test_internal_funding_cancels_out():
    """从组合内现金资产出资买入：WITHDRAW 与 BUY 的外部现金流抵消。"""
    fx = lambda cur, d: D("1")
    txns = [
        txn(trans_type="WITHDRAW", asset_id="CASH_CNY", price=D("1"), quantity=D("10005")),
        txn(trans_type="BUY", price=D("10"), quantity=D("1000"), fee=D("5")),
    ]
    assert net_cash_flow_cny(txns, fx) == D("0.00")


def test_diluted_cost_with_fees_real_ledger():
    """纳指ETF嘉实 2024-12~2026-03 真实流水对账(摊薄含费口径)。"""
    def t(i, tt, d, price, qty, fee):
        return SimpleNamespace(
            id=i, asset_id="159501.SZ", trans_type=tt, trans_date=date(*d),
            price=Decimal(price), quantity=Decimal(qty), fee=Decimal(fee), currency="CNY",
        )

    txns = [
        t(11, "BUY", (2024, 12, 24), "1.5000", "7800", "5"),
        t(12, "BUY", (2025, 2, 5), "1.4950", "6600", "5"),
        t(13, "BUY", (2025, 2, 24), "1.4770", "6700", "5"),
        t(14, "BUY", (2025, 3, 13), "1.3350", "15000", "5"),
        t(15, "BUY", (2025, 4, 3), "1.2980", "15400", "5"),
        t(16, "SELL", (2025, 4, 30), "1.3280", "25700", "5.12"),
        t(17, "BUY", (2026, 2, 26), "1.7030", "5800", "5"),
        t(18, "BUY", (2026, 3, 9), "1.6380", "6100", "5"),
        t(19, "BUY", (2026, 3, 13), "1.6470", "6000", "5"),
        t(20, "BUY", (2026, 3, 17), "1.6500", "6000", "5"),
    ]
    cost = aggregate_diluted_cost(txns)["159501.SZ"]
    # 买入含费 111,128.30+45 − 卖出净回款 34,129.60−5.12 = 77,048.82
    assert cost == D("77048.82")
    # 与券商 App 对账:摊薄单价 ≈ 1.5503,持仓 49,700 股
    assert (cost / D("49700")).quantize(D("0.0001")) == D("1.5503")


def test_diluted_cost_reset_on_full_exit():
    """清仓时成本结转归零;分红加数量不加成本。"""
    txns = [
        SimpleNamespace(id=1, asset_id="A", trans_type="BUY", trans_date=date(2026, 1, 5),
                        price=Decimal("10"), quantity=Decimal("100"), fee=Decimal("5"), currency="CNY"),
        SimpleNamespace(id=2, asset_id="A", trans_type="SELL", trans_date=date(2026, 2, 5),
                        price=Decimal("12"), quantity=Decimal("100"), fee=Decimal("5"), currency="CNY"),
        SimpleNamespace(id=3, asset_id="A", trans_type="BUY", trans_date=date(2026, 3, 5),
                        price=Decimal("11"), quantity=Decimal("100"), fee=Decimal("5"), currency="CNY"),
        SimpleNamespace(id=4, asset_id="B", trans_type="DEPOSIT", trans_date=date(2026, 1, 5),
                        price=Decimal("1"), quantity=Decimal("10000"), fee=Decimal("0"), currency="CNY"),
        SimpleNamespace(id=5, asset_id="B", trans_type="DIVIDEND", trans_date=date(2026, 2, 5),
                        price=Decimal("1"), quantity=Decimal("200"), fee=Decimal("0"), currency="CNY"),
    ]
    out = aggregate_diluted_cost(txns)
    assert out["A"] == D("1105")  # 清仓重置后仅剩新批次含费
    assert out["B"] == D("10000")  # 分红不入成本
