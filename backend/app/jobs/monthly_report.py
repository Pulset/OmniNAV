"""月度/年度报告 Job（任务 4.5）：

调度器每个工作日 20:00 触发，Job 内自检「今天是否本月最后一个交易日」
（无节假日历，与盘中监控的窗口自检同模式），通过才生成月度复盘卡片并推送；
12 月最后一个交易日额外生成年度报告。
手动触发（POST /api/jobs/run/monthly_report?target_date=2026-08-31）跳过自检，
按 target_date 所属期间补算，等价于定时触发。
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import FactPortfolioSnapshot
from app.services.market.fetcher import fetch_latest_market_data
from app.services.notify import notify_all
from app.services.report import (
    build_period_card,
    compute_period_stats,
    is_last_trading_day_of_month,
)
from app.services.settlement import _load_price_book, run_settlement
from app.services.valuation import MissingPriceError

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


async def _load_period_snaps(
    session, start: date, end: date
) -> tuple[FactPortfolioSnapshot | None, list[FactPortfolioSnapshot]]:
    """返回（期初基准快照, 期内快照升序列）。"""
    period_snaps = (
        (
            await session.execute(
                select(FactPortfolioSnapshot)
                .where(
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
            .where(FactPortfolioSnapshot.snapshot_date < start)
            .order_by(FactPortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return start_snap, list(period_snaps)


async def _generate(year: int, month: int | None) -> None:
    """生成并推送一期复盘报告；month=None 为年度报告。"""
    annual = month is None
    if annual:
        start, end = date(year, 1, 1), date(year, 12, 31)
    elif month == 12:
        start, end = date(year, 12, 1), date(year, 12, 31)
    else:
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1)

    label = f"{year}年度" if annual else f"{year}年{month}月"
    async with SessionLocal() as session:
        start_snap, period_snaps = await _load_period_snaps(session, start, end)
        if not period_snaps:
            logger.info("%s 无快照数据，跳过报告", label)
            return

        try:
            await fetch_latest_market_data(session, end)
        except Exception:
            logger.warning("%s 行情抓取失败，估值降级", label, exc_info=True)

        valuations = book = None
        try:
            result = await run_settlement(session, end, persist=False)
        except MissingPriceError as exc:
            logger.warning("%s 期末估值失败（%s），持仓明细降级", label, exc)
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
        await notify_all(title, sections)
        logger.info("%s 报告已推送", label)


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
