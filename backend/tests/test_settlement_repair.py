"""清算链自动修复（P0 修复项）集成测试：

- 冷启动：导入历史后从未生成快照 → detect_replay_start 回首笔交易日，
  全链重放得到正确 NAV（旧逻辑当日按 Day-0 结算会得到 NAV=101 之类的错值）
- 流水变更 → dirty 标记 → 回放覆盖修复，review_notes 保留
- 清仓再入场：全链回放后 NAV 结转而非重置 1.0000
- ensure_chain_current 不含当日（当日留给终局清算）
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.db import SessionLocal
from app.models import (
    DimAsset,
    FactDailyMarketData,
    FactPortfolioSnapshot,
    FactTransaction,
    SysSettlementState,
)
from app.services.settlement import (
    clear_settlement_dirty,
    detect_replay_start,
    ensure_chain_current,
    mark_settlement_dirty,
    replay_settlements,
)

D = Decimal
MT = "600519.SH"
CASH_ID = "CASH_CNY"

D5, D6, D7, D8 = (date(2026, 1, d) for d in (5, 6, 7, 8))
PRICES = [(D5, "10"), (D6, "11"), (D7, "12"), (D8, "12")]


async def _seed_user() -> int:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.security import hash_password
    from app.models import SysUser

    async with SessionLocal() as s:
        user = SysUser(
            username=f"srv_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("password123"),
        )
        s.add(user)
        await s.flush()
        uid = user.id
        s.add(
            DimAsset(
                user_id=uid, asset_id=CASH_ID, name="现金",
                asset_class="CASH", market="CN", currency="CNY",
                valuation_type="CASH",
            )
        )
        s.add(
            DimAsset(
                user_id=uid, asset_id=MT, name="测试股票",
                asset_class="STOCK", market="CN", currency="CNY",
                valuation_type="MARKET",
            )
        )
        # 价格行幂等 upsert：多个测试共享同一测试库
        stmt = pg_insert(FactDailyMarketData).values(
            [
                {"trade_date": d, "symbol": MT, "close_price": D(px)}
                for d, px in PRICES
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_date", "symbol"],
            set_={"close_price": stmt.excluded.close_price},
        )
        await s.execute(stmt)
        await s.commit()
    return uid


async def _add_txn(
    uid: int, asset_id: str, tt: str, d: date, price: str, qty: str
) -> None:
    async with SessionLocal() as s:
        s.add(
            FactTransaction(
                user_id=uid, asset_id=asset_id, trans_type=tt,
                trans_date=d, price=D(price), quantity=D(qty),
                fee=D("0"), currency="CNY",
            )
        )
        await s.commit()


async def _snap(uid: int, d: date) -> FactPortfolioSnapshot | None:
    async with SessionLocal() as s:
        return await s.get(FactPortfolioSnapshot, (uid, d))


async def test_cold_start_replays_from_first_txn(prepared_db):
    """导入历史（d5 买入 1000@10、d7 追买 10@12）无快照：
    检测回首笔日并全链回放，NAV 正确。"""
    uid = await _seed_user()
    await _add_txn(uid, MT, "BUY", D5, "10", "1000")
    await _add_txn(uid, MT, "BUY", D7, "12", "10")

    async with SessionLocal() as s:
        assert await detect_replay_start(s, uid, D8) == D5
        result = await replay_settlements(s, uid, D5, D8)
        await clear_settlement_dirty(s, uid)
        await s.commit()

    s5 = await _snap(uid, D5)
    assert s5.unit_nav == D("1.0000")
    assert s5.total_shares == D("10000.0000")  # 1000 × 10

    s7 = await _snap(uid, D7)
    # d7: 昨日市值 11000 → NAV 1.1；追买 120 按 1.2 增发 100 份
    assert s7.unit_nav == D("1.2000")
    assert s7.total_shares == D("10100.0000")
    assert result.nav.unit_nav == D("1.2000")

    async with SessionLocal() as s:
        assert await detect_replay_start(s, uid, D8) is None


async def test_dirty_marker_replays_and_keeps_notes(prepared_db):
    """已有快照链上补录历史流水：dirty 标记 → 回放覆盖修复，日记保留。"""
    uid = await _seed_user()
    await _add_txn(uid, MT, "BUY", D5, "10", "1000")

    async with SessionLocal() as s:
        await replay_settlements(s, uid, D5, D6)
        s_obj = await s.get(FactPortfolioSnapshot, (uid, D5))
        s_obj.review_notes = "原始日记"
        await s.commit()

    # 补录 d5 另一笔买入（模拟 API 写入口：插流水 + 同事务标记）
    await _add_txn(uid, MT, "BUY", D5, "10", "200")
    async with SessionLocal() as s:
        await mark_settlement_dirty(s, uid, D5)
        await s.commit()
        assert await detect_replay_start(s, uid, D8) == D5
        # 重复标记更晚日期不覆盖更早的失效起点（least 语义）
        await mark_settlement_dirty(s, uid, D6)
        await s.commit()
        assert await detect_replay_start(s, uid, D8) == D5
        await replay_settlements(s, uid, D5, D6)
        await clear_settlement_dirty(s, uid)
        await s.commit()

    s5 = await _snap(uid, D5)
    assert s5.total_shares == D("12000.0000")  # (1000+200) × 10
    assert s5.review_notes == "原始日记"  # 回放不覆盖人工日记
    s6 = await _snap(uid, D6)
    assert s6.unit_nav == D("1.1000")  # 1200×11 / 12000


async def test_mark_skipped_when_no_affected_snapshots(prepared_db):
    """变更日晚于最新快照时无需标记（首个清算日会自然覆盖）。"""
    uid = await _seed_user()
    await _add_txn(uid, MT, "BUY", D5, "10", "1000")
    async with SessionLocal() as s:
        await replay_settlements(s, uid, D5, D6)

    async with SessionLocal() as s:
        await mark_settlement_dirty(s, uid, D8)  # 晚于最新快照 D6
        await s.commit()
        assert await s.get(SysSettlementState, uid) is None
        # 早于首快照的标记被 detect 收敛回首笔交易日
        await mark_settlement_dirty(s, uid, date(2026, 1, 1))
        await s.commit()
        assert await detect_replay_start(s, uid, D8) == D5


async def test_liquidation_then_refund_carries_nav(prepared_db):
    """清仓（d7）后再入金（d8）：全链回放后 NAV 结转 1.1 而非重置 1.0。"""
    uid = await _seed_user()
    await _add_txn(uid, CASH_ID, "DEPOSIT", D5, "1", "100000")
    await _add_txn(uid, CASH_ID, "WITHDRAW", D6, "1", "100000")
    await _add_txn(uid, MT, "BUY", D6, "10", "1000")
    await _add_txn(uid, MT, "SELL", D7, "12", "1000")
    await _add_txn(uid, CASH_ID, "DEPOSIT", D8, "1", "24000")

    async with SessionLocal() as s:
        await replay_settlements(s, uid, D5, D8)

    s7 = await _snap(uid, D7)
    assert s7.total_shares == D("0.0000")  # 清仓
    assert s7.unit_nav == D("1.2000")  # SELL 前市值 1000×12 / 10000 份

    s8 = await _snap(uid, D8)
    assert s8.unit_nav == D("1.2000")  # 结转，旧逻辑此处重置为 1.0000
    assert s8.total_shares == D("20000.0000")  # 24000 / 1.2
    assert s8.daily_return == D("0.0000")
    assert s8.daily_pnl_cny == D("0.00")


async def test_ensure_chain_current_excludes_today(prepared_db):
    """修复到 up_to_exclusive 前一天；当日快照不产生（留给终局清算）。"""
    uid = await _seed_user()
    await _add_txn(uid, MT, "BUY", D5, "10", "1000")
    async with SessionLocal() as s:
        await replay_settlements(s, uid, D5, D6)

    await _add_txn(uid, MT, "BUY", D6, "11", "100")
    async with SessionLocal() as s:
        await mark_settlement_dirty(s, uid, D6)
        await s.commit()
        await ensure_chain_current(s, uid, D8)

    s6 = await _snap(uid, D6)
    assert s6.total_shares == D("11000.0000")  # 10000 + 1100/1.1
    # 历史脏链已修复到 up_to 前一天（D7 落库），D8 当日不落（留给终局清算）
    assert (await _snap(uid, D7)).total_shares == D("11000.0000")
    assert await _snap(uid, D8) is None
    async with SessionLocal() as s:
        assert await s.get(SysSettlementState, uid) is None


@pytest.mark.parametrize(
    "weekend", [date(2026, 1, 10), date(2026, 1, 11)]  # 周六、周日
)
async def test_eod_skips_weekend(prepared_db, weekend, monkeypatch):
    """周末目标日：清算 Job 直接返回，不触库不触网。"""
    from app.jobs import eod_settlement as job_mod

    called = []

    async def _no_fetch(session, as_of):
        called.append(as_of)

    monkeypatch.setattr(job_mod, "fetch_latest_market_data", _no_fetch)
    await job_mod.eod_settlement_job(target_date=weekend)
    assert called == []
