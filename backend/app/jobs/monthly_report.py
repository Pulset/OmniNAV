"""月度/年度报告 Job（任务 4.5 + MultiUser §5.1）：

调度器每个工作日 20:00 触发，Job 内自检「今天是否本月最后一个交易日」
（无节假日历，与盘中监控的窗口自检同模式），通过后按活跃用户循环生成
月度复盘卡片并推送；12 月最后一个交易日额外生成年度报告。
手动触发（POST /api/market/jobs/run/monthly_report?target_date=2026-08-31）
跳过自检，按 target_date 所属期间为全体用户补算，等价于定时触发。
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import FactPortfolioSnapshot, SysUser
from app.services.market.fetcher import fetch_latest_market_data
from app.services.notify import notify_user
from app.services.report import (
    build_period_card,
    compute_period_stats,
    is_last_trading_day_of_month,
)
from app.services.settlement import (
    _load_price_book,
    ensure_chain_current,
    run_settlement,
)
from app.services.valuation import MissingPriceError

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


async def _load_period_snaps(
    session: AsyncSession, user_id: int, start: date, end: date
) -> tuple[FactPortfolioSnapshot | None, list[FactPortfolioSnapshot]]:
    """返回（期初基准快照, 期内快照升序列）。"""
    period_snaps = (
        (
            await session.execute(
                select(FactPortfolioSnapshot)
                .where(
                    FactPortfolioSnapshot.user_id == user_id,
                    FactPortfolioSnapshot.snapshot_date >= start,
                    FactPortfolioSnapshot.snapshot_date <= end,
                )
                .order_by(FactPortfolioSnapshot.snapshot_date.asc())
            )
        )
        .scalars()
        .all()
    )
    start_snap = (
        await session.execute(
            select(FactPortfolioSnapshot)
            .where(
                FactPortfolioSnapshot.user_id == user_id,
                FactPortfolioSnapshot.snapshot_date < start,
            )
            .order_by(FactPortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return start_snap, list(period_snaps)


async def _generate_for_user(
    session: AsyncSession, user: SysUser, year: int, month: int | None
) -> None:
    """为单个用户生成并推送一期复盘报告；month=None 为年度报告。"""
    annual = month is None
    if annual:
        start, end = date(year, 1, 1), date(year, 12, 31)
    elif month == 12:
        start, end = date(year, 12, 1), date(year, 12, 31)
    else:
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1)

    label = f"{year}年度" if annual else f"{year}年{month}月"
    # 快照可能因流水变更而失效，先回放修复到期末前一天
    # （当日留给 06:00 终局清算，保证权威快照口径一致）
    await ensure_chain_current(session, user.id, end)
    start_snap, period_snaps = await _load_period_snaps(session, user.id, start, end)
    if not period_snaps:
        logger.info("user=%s %s 无快照数据，跳过报告", user.id, label)
        return

    try:
        await fetch_latest_market_data(session, end)
    except Exception:
        logger.warning("%s 行情抓取失败，估值降级", label, exc_info=True)

    valuations = book = None
    try:
        result = await run_settlement(session, end, user_id=user.id, persist=False)
    except MissingPriceError as exc:
        logger.warning("user=%s %s 期末估值失败（%s），持仓明细降级", user.id, label, exc)
    else:
        if result is not None:
            valuations = result.valuations
            book = await _load_price_book(session, end)

    stats = compute_period_stats(
        annual=annual,
        year=year,
        month=month,
        start_snap=start_snap,
        period_snaps=period_snaps,
    )
    title, sections = build_period_card(stats, valuations, book)
    await notify_user(session, user.id, title, sections)
    logger.info("user=%s %s 报告已推送", user.id, label)


async def _generate(year: int, month: int | None) -> None:
    """按活跃用户循环生成报告；单用户失败不中断他人。"""
    async with SessionLocal() as session:
        await fetch_latest_market_data(
            session, datetime.now(CST).date()
        )
        users = (
            (
                await session.execute(
                    select(SysUser).where(SysUser.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
    for user in users:
        try:
            async with SessionLocal() as session:
                await _generate_for_user(session, user, year, month)
        except Exception:
            logger.exception(
                "user=%s(%s) 报告生成失败，跳过", user.id, user.username
            )


async def monthly_report_job(target_date: date | None = None) -> None:
    if target_date is None:
        target_date = datetime.now(CST).date()
        if not is_last_trading_day_of_month(target_date):
            return

    logger.info("月度报告开始: %s", target_date)
    await _generate(target_date.year, target_date.month)
    if target_date.month == 12:
        await _generate(target_date.year, None)
    logger.info("月度报告完成")
