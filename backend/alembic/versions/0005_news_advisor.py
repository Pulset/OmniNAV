"""news advisor: fact_news_articles + fact_advice_reports（AI 投资内参）

三时点（盘前 08:45 / 午间 11:45 / 晚间 21:30）新闻 → LLM 内参的存储：
- fact_news_articles：全局新闻池，url_hash 唯一去重（无 URL 源回退标题指纹）
- fact_advice_reports：每用户 × 交易日 × slot 一条，payload 为 LLM 结构化输出

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fact_news_articles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("url", sa.String(1024)),
        sa.Column("url_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_fact_news_published", "fact_news_articles", ["published_at"]
    )
    op.create_table(
        "fact_advice_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("sys_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(8), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(8), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "cited_article_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "token_usage",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id", "trade_date", "slot", name="uq_advice_user_date_slot"
        ),
    )
    op.create_index(
        "ix_fact_advice_user_date", "fact_advice_reports", ["user_id", "trade_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_fact_advice_user_date", table_name="fact_advice_reports")
    op.drop_table("fact_advice_reports")
    op.drop_index("ix_fact_news_published", table_name="fact_news_articles")
    op.drop_table("fact_news_articles")
