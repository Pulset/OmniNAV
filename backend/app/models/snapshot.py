from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FactPortfolioSnapshot(Base):
    __tablename__ = "fact_portfolio_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_market_value_cny: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    unit_nav: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    total_shares: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    daily_pnl_cny: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    daily_return: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    csi300_nav: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sp500_nav: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    nasdaq_nav: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    review_notes: Mapped[str | None] = mapped_column(Text)
