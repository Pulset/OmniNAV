from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DimAsset(Base):
    __tablename__ = "dim_assets"

    # 自然键（如 600519.SH）按用户隔离：多用户可跟踪同一标的
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_users.id"), primary_key=True
    )
    asset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(4), nullable=False, default="CNY")
    valuation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_apr: Mapped[float] = mapped_column(
        Numeric(6, 4), nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
