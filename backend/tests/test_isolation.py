"""多用户数据隔离集成测试（MultiUser §4.4，随 M2 交付）。

覆盖：未登录全 401、双用户数据互不可见、跨用户 404、
admin 用户管理、改密/停用吊销会话、登录限速。
"""

from datetime import date

from tests.conftest import TEST_PASSWORD, new_client, register_user, do_login  # noqa: F401


def _uid() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


async def test_unauthenticated_returns_401(prepared_db):
    async with new_client() as client:
        protected = [
            ("GET", "/api/assets"),
            ("POST", "/api/assets"),
            ("GET", "/api/transactions"),
            ("POST", "/api/transactions"),
            ("GET", "/api/portfolio/holdings"),
            ("GET", "/api/portfolio/summary"),
            ("GET", "/api/snapshots"),
            ("GET", "/api/alert-rules"),
            ("GET", "/api/metrics/summary"),
            ("GET", "/api/market/prices?symbol=CSI300"),
            ("POST", "/api/market/jobs/run/eod_settlement"),
            ("GET", "/api/auth/me"),
            ("GET", "/api/admin/users"),
        ]
        for method, path in protected:
            resp = await client.request(method, path)
            assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"
        # 健康检查与登录本身不要求登录
        assert (await client.get("/api/health")).status_code == 200


def _asset_payload(asset_id: str) -> dict:
    return {
        "asset_id": asset_id,
        "name": f"测试资产 {asset_id}",
        "asset_class": "STOCK",
        "market": "CN",
        "currency": "CNY",
        "valuation_type": "MARKET",
    }


async def test_two_users_isolated(prepared_db, register_user, do_login):
    uid = _uid()
    await register_user(f"alice_{uid}")
    bob_id = await register_user(f"bob_{uid}")

    async with new_client() as alice, new_client() as bob:
        await do_login(alice, f"alice_{uid}")
        await do_login(bob, f"bob_{uid}")

        # 各建资产与流水
        resp = await alice.post("/api/assets", json=_asset_payload(f"AL_{uid}"))
        assert resp.status_code == 201, resp.text
        resp = await bob.post("/api/assets", json=_asset_payload(f"BO_{uid}"))
        assert resp.status_code == 201, resp.text

        resp = await alice.post(
            "/api/transactions",
            json={
                "asset_id": f"AL_{uid}",
                "trans_type": "BUY",
                "trans_date": "2026-09-01",
                "price": "10",
                "quantity": "100",
                "fee": "5",
                "currency": "CNY",
            },
        )
        assert resp.status_code == 201, resp.text
        alice_txn_id = resp.json()["id"]

        # 列表互不可见
        alice_ids = {a["asset_id"] for a in (await alice.get("/api/assets")).json()}
        bob_ids = {a["asset_id"] for a in (await bob.get("/api/assets")).json()}
        assert f"AL_{uid}" in alice_ids and f"BO_{uid}" not in alice_ids
        assert f"BO_{uid}" in bob_ids and f"AL_{uid}" not in bob_ids

        alice_txns = (await alice.get("/api/transactions")).json()
        assert [t["id"] for t in alice_txns] == [alice_txn_id]
        assert (await bob.get("/api/transactions")).json() == []

        # 跨用户资产访问一律 404，不泄露存在性
        assert (
            await alice.put(f"/api/assets/BO_{uid}", json={"name": "hijack"})
        ).status_code == 404
        assert (await alice.delete(f"/api/assets/BO_{uid}")).status_code == 404
        # alice 不能给 bob 的资产记账
        resp = await alice.post(
            "/api/transactions",
            json={
                "asset_id": f"BO_{uid}",
                "trans_type": "BUY",
                "trans_date": "2026-09-01",
                "price": "1",
                "quantity": "1",
                "currency": "CNY",
            },
        )
        assert resp.status_code == 404
        # bob 不能改/删 alice 的流水
        assert (
            await bob.put(
                f"/api/transactions/{alice_txn_id}",
                json={
                    "asset_id": f"BO_{uid}",
                    "trans_type": "BUY",
                    "trans_date": "2026-09-01",
                    "price": "1",
                    "quantity": "1",
                    "currency": "CNY",
                },
            )
        ).status_code == 404
        assert (await bob.delete(f"/api/transactions/{alice_txn_id}")).status_code == 404

        # 告警规则：bob 不能动 alice 的规则
        resp = await alice.post(
            "/api/alert-rules",
            json={"rule_type": "DAILY_PCT_CHANGE", "asset_id": f"AL_{uid}", "threshold": 0.05},
        )
        assert resp.status_code == 201, resp.text
        alice_rule_id = resp.json()["id"]
        assert (
            await bob.put(f"/api/alert-rules/{alice_rule_id}", json={"is_active": False})
        ).status_code == 404
        assert (
            await bob.delete(f"/api/alert-rules/{alice_rule_id}")
        ).status_code == 404

        # 快照按用户隔离：直接给 bob 插一条快照，alice 看不到也改不了
        from decimal import Decimal

        from app.core.db import SessionLocal
        from app.models import FactPortfolioSnapshot

        async with SessionLocal() as session:
            session.add(
                FactPortfolioSnapshot(
                    user_id=bob_id,
                    snapshot_date=date(2026, 9, 1),
                    total_market_value_cny=Decimal("100"),
                    unit_nav=Decimal("1"),
                    total_shares=Decimal("100"),
                    daily_pnl_cny=Decimal("0"),
                    daily_return=Decimal("0"),
                )
            )
            await session.commit()

        bob_snaps = (await bob.get("/api/snapshots")).json()
        assert len(bob_snaps) == 1
        assert (await alice.get("/api/snapshots")).json() == []
        resp = await alice.patch(
            "/api/snapshots/2026-09-01", json={"review_notes": "hack"}
        )
        assert resp.status_code == 404
        resp = await bob.patch(
            "/api/snapshots/2026-09-01", json={"review_notes": "bob 的日记"}
        )
        assert resp.status_code == 200


async def test_member_cannot_access_admin(prepared_db, register_user, do_login):
    uid = _uid()
    await register_user(f"member_{uid}")
    async with new_client() as member:
        await do_login(member, f"member_{uid}")
        assert (await member.get("/api/admin/users")).status_code == 403
        resp = await member.post(
            "/api/admin/users",
            json={"username": "x", "password": TEST_PASSWORD, "role": "admin"},
        )
        assert resp.status_code == 403


async def test_admin_user_management(prepared_db, register_user, do_login):
    uid = _uid()
    admin_name, member_name = f"root_{uid}", f"m_{uid}"
    await register_user(admin_name, role="admin")
    async with new_client() as admin:
        await do_login(admin, admin_name)

        # 建号
        resp = await admin.post(
            "/api/admin/users",
            json={"username": member_name, "password": TEST_PASSWORD, "role": "member"},
        )
        assert resp.status_code == 201, resp.text
        member_id = resp.json()["id"]

        # 列表包含新用户
        users = (await admin.get("/api/admin/users")).json()
        assert member_name in {u["username"] for u in users}

        # 不能停用自己
        admin_id = next(u["id"] for u in users if u["username"] == admin_name)
        resp = await admin.patch(
            f"/api/admin/users/{admin_id}", json={"is_active": False}
        )
        assert resp.status_code == 422

        # 重置密码后，成员用旧密码无法登录、新密码可以
        resp = await admin.patch(
            f"/api/admin/users/{member_id}", json={"password": "newpass456"}
        )
        assert resp.status_code == 200
        async with new_client() as member:
            resp = await member.post(
                "/api/auth/login",
                json={"username": member_name, "password": TEST_PASSWORD},
            )
            assert resp.status_code == 401
            await do_login(member, member_name, "newpass456")

        # 停用后成员会话即时失效、无法再登录
        async with new_client() as member:
            await do_login(member, member_name, "newpass456")
            await admin.patch(
                f"/api/admin/users/{member_id}", json={"is_active": False}
            )
            assert (await member.get("/api/auth/me")).status_code == 401
            resp = await member.post(
                "/api/auth/login",
                json={"username": member_name, "password": "newpass456"},
            )
            assert resp.status_code == 401


async def test_change_password_revokes_sessions(prepared_db, register_user, do_login):
    uid = _uid()
    await register_user(f"cp_{uid}")
    async with new_client() as client:
        await do_login(client, f"cp_{uid}")

        # 原密码错误
        resp = await client.put(
            "/api/auth/me/password",
            json={"old_password": "wrong", "new_password": "newpass789"},
        )
        assert resp.status_code == 422

        resp = await client.put(
            "/api/auth/me/password",
            json={"old_password": TEST_PASSWORD, "new_password": "newpass789"},
        )
        assert resp.status_code == 200
        # 全部会话已吊销
        assert (await client.get("/api/auth/me")).status_code == 401

        async with new_client() as fresh:
            await do_login(fresh, f"cp_{uid}", "newpass789")


async def test_notifications_settings(prepared_db, register_user, do_login):
    uid = _uid()
    await register_user(f"nt_{uid}")
    async with new_client() as client:
        await do_login(client, f"nt_{uid}")
        assert ((await client.get("/api/auth/me/notifications")).json()) == {
            "feishu_webhook_url": None,
            "telegram_bot_token": None,
            "telegram_chat_id": None,
        }
        resp = await client.put(
            "/api/auth/me/notifications",
            json={"feishu_webhook_url": "https://example.com/hook"},
        )
        assert resp.status_code == 200
        assert (
            await client.get("/api/auth/me/notifications")
        ).json()["feishu_webhook_url"] == "https://example.com/hook"


async def test_login_rate_limit(prepared_db, register_user):
    uid = _uid()
    username = f"rl_{uid}"
    await register_user(username)
    async with new_client() as client:
        for _ in range(5):
            resp = await client.post(
                "/api/auth/login",
                json={"username": username, "password": "totally-wrong"},
            )
            assert resp.status_code == 401
        # 第 6 次起限速拒绝，正确密码也被拒
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": TEST_PASSWORD}
        )
        assert resp.status_code == 429
