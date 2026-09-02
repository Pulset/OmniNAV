from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FactDailyMarketData(Base):
    __tablename__ = "fact_daily_market_data"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
