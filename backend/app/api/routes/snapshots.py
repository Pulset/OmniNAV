"""净值快照查询与复盘日记（PRD §3.4）。数据按用户隔离。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import FactPortfolioSnapshot, SysUser
from app.schemas import SnapshotNotesIn, SnapshotOut

router = APIRouter(
    prefix="/snapshots", tags=["snapshots"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[SnapshotOut])
async def list_snapshots(
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 1000,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(FactPortfolioSnapshot)
        .where(FactPortfolioSnapshot.user_id == user.id)
        .order_by(FactPortfolioSnapshot.snapshot_date.asc())
        .limit(limit)
    )
    if date_from:
        q = q.where(FactPortfolioSnapshot.snapshot_date >= date_from)
    if date_to:
        q = q.where(FactPortfolioSnapshot.snapshot_date <= date_to)
    return (await session.execute(q)).scalars().all()


@router.patch("/{snapshot_date}", response_model=SnapshotOut)
async def update_review_notes(
    snapshot_date: date,
    payload: SnapshotNotesIn,
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    snap = await session.get(FactPortfolioSnapshot, (user.id, snapshot_date))
    if not snap:
        raise HTTPException(404, f"{snapshot_date} 无快照，请先运行清算")
    snap.review_notes = payload.review_notes
    await session.commit()
    await session.refresh(snap)
    return snap
