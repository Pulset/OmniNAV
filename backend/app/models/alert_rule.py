from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SysAlertRule(Base):
    __tablename__ = "sys_alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asset_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("dim_assets.asset_id")
    )
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
