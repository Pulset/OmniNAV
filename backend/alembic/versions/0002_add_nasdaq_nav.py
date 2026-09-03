"""add nasdaq_nav benchmark column to fact_portfolio_snapshots

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fact_portfolio_snapshots",
        sa.Column("nasdaq_nav", sa.Numeric(12, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fact_portfolio_snapshots", "nasdaq_nav")
