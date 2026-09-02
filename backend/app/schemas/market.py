from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ManualNavIn(BaseModel):
    """净值型理财（MANUAL_NAV）手动录入最新单位净值。"""

    nav_date: date
    nav: Decimal = Field(gt=0, max_digits=18, decimal_places=4)


class MarketPriceOut(BaseModel):
    trade_date: date
    symbol: str
    close_price: Decimal
