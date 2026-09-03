"""量化指标：夏普 / 最大回撤 / 波动率 / 对标 Alpha-Beta（PRD §3.4 月度复盘）。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import FactPortfolioSnapshot, SysUser
from app.services.metrics import compute_metric_summary

router = APIRouter(
    prefix="/metrics", tags=["metrics"], dependencies=[Depends(get_current_user)]
)


@router.get("/summary")
async def metric_summary(
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    snaps = (
        (
            await session.execute(
                select(FactPortfolioSnapshot)
                .where(FactPortfolioSnapshot.user_id == user.id)
                .order_by(FactPortfolioSnapshot.snapshot_date.asc())
            )
        )
        .scalars()
        .all()
    )
    return compute_metric_summary(
        dates=[s.snapshot_date for s in snaps],
        unit_navs=[float(s.unit_nav) for s in snaps],
        csi300_navs=[float(s.csi300_nav) if s.csi300_nav else None for s in snaps],
    )
