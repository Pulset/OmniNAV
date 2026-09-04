"""写入口守卫（P0/P1 修复项）API 集成测试：

- 超卖在写入口拒绝（新增/修改/删除路径），不再等到每日清算才爆
- 币种白名单：无汇率源的币种 422
- MANUAL_NAV 净值按用户隔离：同 asset_id 双用户互不覆盖
- Job 手动触发仅管理员，且非管理员 403
"""

from datetime import date
from decimal import Decimal

from tests.conftest import new_client, register_user, do_login  # noqa: F401


def _uid() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def _market_asset(asset_id: str) -> dict:
    return {
        "asset_id": asset_id,
        "name": f"股票 {asset_id}",
        "asset_class": "STOCK",
        "market": "CN",
        "currency": "CNY",
        "valuation_type": "MARKET",
    }


def _buy(asset_id: str, qty: str, d: str = "2026-09-01", price: str = "10") -> dict:
    return {
        "asset_id": asset_id,
        "trans_type": "BUY",
        "trans_date": d,
        "price": price,
        "quantity": qty,
        "currency": "CNY",
    }


async def test_oversell_rejected_at_write_time(prepared_db, register_user, do_login):  # noqa: F401
    uid = _uid()
    await register_user(f"os_{uid}")
    aid = f"MT_{uid}.SH"
    async with new_client() as client:
        await do_login(client, f"os_{uid}")
        assert (await client.post("/api/assets", json=_market_asset(aid))).status_code == 201
        assert (await client.post("/api/transactions", json=_buy(aid, "100"))).status_code == 201

        # 新增超卖 → 422
        sell_200 = _buy(aid, "200")
        sell_200["trans_type"] = "SELL"
        resp = await client.post("/api/transactions", json=sell_200)
        assert resp.status_code == 422
        assert "超过持仓" in resp.json()["detail"]

        # 正常卖出 → 201
        sell_100 = _buy(aid, "100", d="2026-09-02")
        sell_100["trans_type"] = "SELL"
        resp = await client.post("/api/transactions", json=sell_100)
        assert resp.status_code == 201, resp.text
        sell_id = resp.json()["id"]

        # 修改数量为 150（超卖）→ 422
        sell_150 = dict(sell_100, quantity="150")
        resp = await client.put(f"/api/transactions/{sell_id}", json=sell_150)
        assert resp.status_code == 422

        # 删除前置买入会令卖出超卖 → 422
        txns = (await client.get("/api/transactions")).json()
        buy_id = next(t["id"] for t in txns if t["trans_type"] == "BUY")
        resp = await client.delete(f"/api/transactions/{buy_id}")
        assert resp.status_code == 422


async def test_same_day_buy_then_sell_ordering(prepared_db, register_user, do_login):  # noqa: F401
    """同日先买后卖：校验重放必须保持时序，不得误判超卖。"""
    uid = _uid()
    await register_user(f"sd_{uid}")
    aid = f"MT_{uid}.SH"
    async with new_client() as client:
        await do_login(client, f"sd_{uid}")
        assert (await client.post("/api/assets", json=_market_asset(aid))).status_code == 201
        assert (
            await client.post("/api/transactions", json=_buy(aid, "100"))
        ).status_code == 201

        # 同日卖出 50：新增流水排在同日已有买入之后
        sell = _buy(aid, "50")
        sell["trans_type"] = "SELL"
        resp = await client.post("/api/transactions", json=sell)
        assert resp.status_code == 201, resp.text
        sell_id = resp.json()["id"]

        # 同日再改这笔卖出为 100（恰好清仓）：修改沿用原 id，时序不变
        resp = await client.put(
            f"/api/transactions/{sell_id}", json=dict(sell, quantity="100")
        )
        assert resp.status_code == 200, resp.text


async def test_currency_whitelist(prepared_db, register_user, do_login):  # noqa: F401
    uid = _uid()
    await register_user(f"cw_{uid}")
    async with new_client() as client:
        await do_login(client, f"cw_{uid}")
        resp = await client.post(
            "/api/assets", json=dict(_market_asset(f"EU_{uid}.SH"), currency="EUR")
        )
        assert resp.status_code == 422
        assert "EUR" in resp.json()["detail"][0]["msg"] or "EUR" in str(resp.json())


async def test_manual_nav_user_isolation(prepared_db, register_user, do_login):  # noqa: F401
    from app.core.db import SessionLocal
    from app.models import FactManualNav
    from app.services.valuation import manual_nav_symbol

    uid = _uid()
    alice_id = await register_user(f"mn_a_{uid}")
    bob_id = await register_user(f"mn_b_{uid}")

    asset = {
        "asset_id": "WM001",
        "name": "同名理财",
        "asset_class": "WEALTH",
        "market": "CN",
        "currency": "CNY",
        "valuation_type": "MANUAL_NAV",
    }
    async with new_client() as alice, new_client() as bob:
        await do_login(alice, f"mn_a_{uid}")
        await do_login(bob, f"mn_b_{uid}")
        assert (await alice.post("/api/assets", json=asset)).status_code == 201
        assert (await bob.post("/api/assets", json=asset)).status_code == 201

        resp = await alice.post(
            "/api/market/manual-nav/WM001",
            json={"nav_date": "2026-09-01", "nav": "1.0500"},
        )
        assert resp.status_code == 201, resp.text
        resp = await bob.post(
            "/api/market/manual-nav/WM001",
            json={"nav_date": "2026-09-01", "nav": "0.9800"},
        )
        assert resp.status_code == 201, resp.text

    from sqlalchemy import select

    async with SessionLocal() as s:
        rows = (
            (
                await s.execute(
                    select(FactManualNav).where(FactManualNav.asset_id == "WM001")
                )
            )
            .scalars()
            .all()
        )
    assert {r.user_id: r.nav for r in rows} == {
        alice_id: Decimal("1.05"),
        bob_id: Decimal("0.98"),
    }

    # 估值走各自命名空间净值
    from app.services.settlement import _load_price_book

    async with SessionLocal() as s:
        for user_id, expect in ((alice_id, "1.05"), (bob_id, "0.98")):
            book = await _load_price_book(
                s, date(2026, 9, 1), user_id=user_id
            )
            got = book.close(manual_nav_symbol("WM001"), date(2026, 9, 1))
            assert got == Decimal(expect)


async def test_job_trigger_admin_only(prepared_db, register_user, do_login):  # noqa: F401
    uid = _uid()
    await register_user(f"jt_{uid}")
    async with new_client() as client:
        await do_login(client, f"jt_{uid}")
        resp = await client.post("/api/market/jobs/run/eod_settlement")
        assert resp.status_code == 403
