from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FactDailyMarketData(Base):
    __tablename__ = "fact_daily_market_data"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)


class FactManualNav(Base):
    """MANUAL_NAV 资产的用户私有净值历史。

    手动净值是每用户的业务数据（不同用户可跟踪不同产品却撞 asset_id），
    不能混入全局共享的 fact_daily_market_data。
    """

    __tablename__ = "fact_manual_navs"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("sys_users.id"), primary_key=True
    )
    asset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nav_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "asset_id"],
            ["dim_assets.user_id", "dim_assets.asset_id"],
            name="fact_manual_navs_user_asset_fkey",
        ),
    )
