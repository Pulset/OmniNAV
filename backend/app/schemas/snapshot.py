from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_date: date
    total_market_value_cny: Decimal
    unit_nav: Decimal
    total_shares: Decimal
    daily_pnl_cny: Decimal
    daily_return: Decimal
    csi300_nav: Decimal | None
    sp500_nav: Decimal | None
    nasdaq_nav: Decimal | None
    review_notes: str | None


class SnapshotNotesIn(BaseModel):
    review_notes: str | None = Field(default=None, max_length=4000)


class NavHistoryPoint(BaseModel):
    """净值曲线数据点（组合与基准统一归一化，起点 1.0）。"""

    date: date
    nav: Decimal
    csi300_nav: Decimal | None = None
    sp500_nav: Decimal | None = None
    nasdaq_nav: Decimal | None = None
    total_mv_cny: Decimal
    daily_return: Decimal
