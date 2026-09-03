"""APScheduler 调度装配（技术方案 §4 三阶段流水线）。

- 22:00 A股日终简报 / 06:00 终局清算：cron 单点触发
- 盘中微监控：交易日 09:00–23:00 每 15 分钟（Job 内自检 09:30 窗口）
- 月度报告：每工作日 20:00 触发（Job 内自检「本月最后一个交易日」）
"""

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.eod_settlement import eod_settlement_job
from app.jobs.evening_brief import evening_brief_job
from app.jobs.intraday_monitor import intraday_monitor_job
from app.jobs.monthly_report import monthly_report_job

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")

JOB_REGISTRY = {
    "eod_settlement": eod_settlement_job,
    "evening_brief": evening_brief_job,
    "intraday_monitor": intraday_monitor_job,
    "monthly_report": monthly_report_job,
}


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=CST)
    scheduler.add_job(
        eod_settlement_job,
        CronTrigger(hour=6, minute=0, timezone=CST),
        id="eod_settlement",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        evening_brief_job,
        CronTrigger(hour=22, minute=0, timezone=CST),
        id="evening_brief",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        intraday_monitor_job,
        CronTrigger(day_of_week="mon-fri", hour="9-22", minute="*/15", timezone=CST),
        id="intraday_monitor",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        monthly_report_job,
        CronTrigger(day_of_week="mon-fri", hour=20, minute=0, timezone=CST),
        id="monthly_report",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    return scheduler
