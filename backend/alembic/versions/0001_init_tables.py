"""init: create 5 core tables (TechnicalArchitecture SS5 DDL)

Revision ID: 0001
Revises:
Create Date: 2026-09-02

- dim_assets               标的资产维度表
- fact_transactions        交易流水事实表
- fact_daily_market_data   每日行情与汇率历史表
- fact_portfolio_snapshots 组合每日净值快照表
- sys_alert_rules          监控预警规则配置表
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dim_assets",
        sa.Column("asset_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("asset_class", sa.String(16), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("currency", sa.String(4), nullable=False, server_default="CNY"),
        sa.Column("valuation_type", sa.String(16), nullable=False),
        sa.Column("expected_apr", sa.Numeric(6, 4), server_default="0.0000"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "fact_transactions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "asset_id",
            sa.String(32),
            sa.ForeignKey("dim_assets.asset_id"),
            nullable=False,
        ),
        sa.Column("trans_type", sa.String(16), nullable=False),
        sa.Column("trans_date", sa.Date, nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("fee", sa.Numeric(12, 2), server_default="0.00"),
        sa.Column("currency", sa.String(4), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_txn_trans_date", "fact_transactions", ["trans_date"])
    op.create_index("ix_txn_asset_id", "fact_transactions", ["asset_id"])

    op.create_table(
        "fact_daily_market_data",
        sa.Column("trade_date", sa.Date, primary_key=True),
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("close_price", sa.Numeric(18, 4), nullable=False),
    )

    op.create_table(
        "fact_portfolio_snapshots",
        sa.Column("snapshot_date", sa.Date, primary_key=True),
        sa.Column("total_market_value_cny", sa.Numeric(18, 2), nullable=False),
        sa.Column("unit_nav", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_shares", sa.Numeric(18, 4), nullable=False),
        sa.Column("daily_pnl_cny", sa.Numeric(18, 2), nullable=False),
        sa.Column("daily_return", sa.Numeric(8, 4), nullable=False),
        sa.Column("csi300_nav", sa.Numeric(12, 4)),
        sa.Column("sp500_nav", sa.Numeric(12, 4)),
        sa.Column("review_notes", sa.Text()),
    )

    op.create_table(
        "sys_alert_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(32), sa.ForeignKey("dim_assets.asset_id")),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Numeric(8, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_table("sys_alert_rules")
    op.drop_table("fact_portfolio_snapshots")
    op.drop_table("fact_daily_market_data")
    op.drop_index("ix_txn_asset_id", table_name="fact_transactions")
    op.drop_index("ix_txn_trans_date", table_name="fact_transactions")
    op.drop_table("fact_transactions")
    op.drop_table("dim_assets")
