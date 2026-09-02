from decimal import Decimal

from pydantic import BaseModel


class HoldingOut(BaseModel):
    asset_id: str
    name: str
    asset_class: str
    market: str
    currency: str
    valuation_type: str
    quantity: Decimal
    unit_price: Decimal
    fx_rate: Decimal
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal | None
    day_change_pct: Decimal | None
    weight: Decimal


class HoldingsResponse(BaseModel):
    base_currency: str
    as_of: str
    total_value: Decimal
    total_cost: Decimal
    holdings: list[HoldingOut]
    allocation_by_class: dict[str, Decimal]
    allocation_by_market: dict[str, Decimal]


class SnapshotBrief(BaseModel):
    date: str
    unit_nav: Decimal
    daily_return: Decimal
    daily_pnl_cny: Decimal
    total_market_value_cny: Decimal
    cumulative_return: Decimal


class SummaryResponse(BaseModel):
    base_currency: str
    latest: SnapshotBrief | None
    prev: SnapshotBrief | None
    snapshot_count: int
