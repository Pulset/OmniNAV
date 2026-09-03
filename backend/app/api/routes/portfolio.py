"""组合实时视图：当前持仓估值（支持基准币种切换 CNY/USD）。数据按用户隔离。"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import (
    DimAsset,
    FactDailyMarketData,
    FactPortfolioSnapshot,
    FactTransaction,
    SysUser,
)
from app.schemas.portfolio import (
    HoldingsResponse,
    HoldingOut,
    SnapshotBrief,
    SummaryResponse,
)
from app.services.nav import ZERO
from app.services.portfolio import aggregate_diluted_cost, aggregate_holdings
from app.services.settlement import _load_price_book, _to_asset_like
from app.services.valuation import MissingPriceError, fx_symbol, value_asset

router = APIRouter(
    prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(get_current_user)]
)

Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")


async def _current_valuations(
    session: AsyncSession, user_id: int, as_of: date
):
    txns = (
        (
            await session.execute(
                select(FactTransaction).where(FactTransaction.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    holdings = aggregate_holdings(txns)
    diluted = aggregate_diluted_cost(txns)
    assets = {
        a.asset_id: _to_asset_like(a)
        for a in (
            await session.execute(
                select(DimAsset).where(DimAsset.user_id == user_id)
            )
        ).scalars()
    }
    book = await _load_price_book(session, as_of, user_id=user_id)
    valuations = [
        value_asset(assets[aid], lots, book, as_of, diluted_cost=diluted.get(aid))
        for aid, lots in holdings.items()
        if aid in assets
    ]
    return book, valuations


def _brief(snap: FactPortfolioSnapshot) -> SnapshotBrief:
    return SnapshotBrief(
        date=snap.snapshot_date.isoformat(),
        unit_nav=Decimal(snap.unit_nav),
        daily_return=Decimal(snap.daily_return),
        daily_pnl_cny=Decimal(snap.daily_pnl_cny),
        total_market_value_cny=Decimal(snap.total_market_value_cny),
        cumulative_return=(Decimal(snap.unit_nav) - Decimal("1")).quantize(Q4),
    )


@router.get("/holdings", response_model=HoldingsResponse)
async def get_holdings(
    base: str = Query(default="CNY", pattern=r"^(CNY|USD)$"),
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    as_of = date.today()
    try:
        book, valuations = await _current_valuations(session, user.id, as_of)
        base_rate = (
            Decimal("1")
            if base == "CNY"
            else book.fx_to_cny("USD", as_of)
        )
    except MissingPriceError as exc:
        raise HTTPException(503, str(exc))

    def to_base(v_cny: Decimal) -> Decimal:
        return (v_cny / base_rate).quantize(Q2, ROUND_HALF_UP)

    total = sum((v.market_value_cny for v in valuations), ZERO)
    items = [
        HoldingOut(
            asset_id=v.asset.asset_id,
            name=v.asset.name,
            asset_class=v.asset.asset_class,
            market=v.asset.market,
            currency=v.asset.currency,
            valuation_type=v.asset.valuation_type,
            quantity=v.quantity,
            unit_price=v.unit_price,
            fx_rate=v.fx_rate,
            market_value=to_base(v.market_value_cny),
            cost_basis=to_base(v.cost_basis_cny),
            unrealized_pnl=to_base(v.market_value_cny - v.cost_basis_cny),
            unrealized_pnl_pct=(
                (v.market_value_cny / v.cost_basis_cny - 1).quantize(Q4)
                if v.cost_basis_cny > ZERO
                else None
            ),
            day_change_pct=v.day_change_pct,
            weight=(v.market_value_cny / total).quantize(Q4) if total > ZERO else ZERO,
        )
        for v in sorted(valuations, key=lambda x: -x.market_value_cny)
    ]

    def _alloc(key: str) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for v in valuations:
            k = getattr(v.asset, key)
            out[k] = out.get(k, ZERO) + v.market_value_cny
        return {
            k: (x / total).quantize(Q4)
            for k, x in sorted(out.items(), key=lambda kv: -kv[1])
        } if total > ZERO else {}

    return HoldingsResponse(
        base_currency=base,
        as_of=as_of.isoformat(),
        total_value=to_base(total),
        total_cost=to_base(sum((v.cost_basis_cny for v in valuations), ZERO)),
        holdings=items,
        allocation_by_class=_alloc("asset_class"),
        allocation_by_market=_alloc("market"),
    )


@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    base: str = Query(default="CNY", pattern=r"^(CNY|USD)$"),
    user: SysUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    snaps = (
        (
            await session.execute(
                select(FactPortfolioSnapshot)
                .where(FactPortfolioSnapshot.user_id == user.id)
                .order_by(FactPortfolioSnapshot.snapshot_date.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    count = (
        await session.execute(
            select(func.count())
            .select_from(FactPortfolioSnapshot)
            .where(FactPortfolioSnapshot.user_id == user.id)
        )
    ).scalar_one()
    return SummaryResponse(
        base_currency=base,
        latest=_brief(snaps[0]) if snaps else None,
        prev=_brief(snaps[1]) if len(snaps) > 1 else None,
        snapshot_count=count,
    )
