"""manual nav per-user isolation + settlement dirty state

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03

1. fact_manual_navs：MANUAL_NAV 手动净值改为按用户隔离存储；
   存量数据从 fact_daily_market_data 按 dim_assets(valuation_type='MANUAL_NAV')
   JOIN 迁出（沿用 0003 的归属约定：单用户时代数据归各资产所属用户；
   多用户时代同 asset_id 撞车的行会被双方各得一份副本，属可接受的降级）。
2. sys_settlement_state：流水变更后的快照失效标记（dirty_from），
   供 06:00/22:00 Job 自动逐日回放修复清算链。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fact_manual_navs",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(18, 6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"]),
        sa.ForeignKeyConstraint(
            ["user_id", "asset_id"],
            ["dim_assets.user_id", "dim_assets.asset_id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "asset_id", "nav_date"),
    )
    # 存量手动净值迁出全局行情表
    op.execute(
        """
        INSERT INTO fact_manual_navs (user_id, asset_id, nav_date, nav)
        SELECT d.user_id, d.asset_id, m.trade_date, m.close_price
        FROM fact_daily_market_data m
        JOIN dim_assets d
          ON d.asset_id = m.symbol AND d.valuation_type = 'MANUAL_NAV'
        """
    )
    op.execute(
        """
        DELETE FROM fact_daily_market_data m
        USING dim_assets d
        WHERE d.asset_id = m.symbol AND d.valuation_type = 'MANUAL_NAV'
        """
    )

    op.create_table(
        "sys_settlement_state",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("dirty_from", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    # 手动净值不回迁全局表：多用户下同 asset_id 会互相覆盖，
    # 回滚后 MANUAL_NAV 估值回退加权成本（可接受的降级）
    op.drop_table("sys_settlement_state")
    op.drop_table("fact_manual_navs")
