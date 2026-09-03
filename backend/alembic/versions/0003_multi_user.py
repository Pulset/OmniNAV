"""multi-user: sys_users/user_settings + 4 表 user_id 隔离 + 存量数据归属 admin

MultiUser §6 单次迁移按序完成：
1. 建 sys_users / user_settings
2. seed 首个 admin（INIT_ADMIN_USERNAME / INIT_ADMIN_PASSWORD），并把 .env 的
   通知配置回填其 user_settings；此后以表内配置为准
3. 四张业务表 ADD COLUMN user_id（nullable）→ 回填 admin_id → SET NOT NULL
4. 删旧主键/外键，建复合主键、复合外键与索引（fact_daily_market_data 不动）

downgrade 恢复单用户表结构；若已存在多用户且自然键冲突，回滚会因主键冲突失败。

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings
from app.core.security import hash_password

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _seed_admin_and_settings() -> int:
    """创建首 admin 并回填 .env 通知配置，返回 admin_id。"""
    settings = get_settings()
    username = settings.init_admin_username
    if not settings.init_admin_password:
        raise RuntimeError(
            "INIT_ADMIN_PASSWORD 未设置：首管理员 seed 需要初始密码，"
            "请在 backend/.env 中设置后重新执行 alembic upgrade head"
        )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO sys_users (username, password_hash, role, is_active) "
            "VALUES (:u, :p, 'admin', TRUE)"
        ),
        {"u": username, "p": hash_password(settings.init_admin_password)},
    )
    admin_id = bind.execute(
        sa.text("SELECT id FROM sys_users WHERE username = :u"), {"u": username}
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO user_settings "
            "(user_id, feishu_webhook_url, telegram_bot_token, telegram_chat_id) "
            "VALUES (:uid, :feishu, :tg_token, :tg_chat)"
        ),
        {
            "uid": admin_id,
            "feishu": settings.feishu_webhook_url,
            "tg_token": settings.telegram_bot_token,
            "tg_chat": settings.telegram_chat_id,
        },
    )
    return admin_id


def upgrade() -> None:
    # 1. 账号表
    op.create_table(
        "sys_users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(8), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "user_settings",
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("sys_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("feishu_webhook_url", sa.String(255)),
        sa.Column("telegram_bot_token", sa.String(255)),
        sa.Column("telegram_chat_id", sa.String(64)),
    )

    # 2. seed 首 admin（含 .env 通知配置回填）
    admin_id = _seed_admin_and_settings()

    # 3. 四张业务表加 user_id（先 nullable）→ 回填 → NOT NULL
    for table in (
        "dim_assets",
        "fact_transactions",
        "fact_portfolio_snapshots",
        "sys_alert_rules",
    ):
        op.add_column(
            table,
            sa.Column("user_id", sa.BigInteger, sa.ForeignKey("sys_users.id")),
        )
        op.execute(
            sa.text(f"UPDATE {table} SET user_id = :uid").bindparams(uid=admin_id)
        )
        op.alter_column(table, "user_id", existing_type=sa.BigInteger(), nullable=False)

    # 4. 重建主键/外键（先删依赖旧主键的外键）
    op.drop_constraint(
        "fact_transactions_asset_id_fkey", "fact_transactions", type_="foreignkey"
    )
    op.drop_constraint(
        "sys_alert_rules_asset_id_fkey", "sys_alert_rules", type_="foreignkey"
    )
    op.drop_constraint("dim_assets_pkey", "dim_assets", type_="primary")
    op.drop_constraint(
        "fact_portfolio_snapshots_pkey", "fact_portfolio_snapshots", type_="primary"
    )

    op.create_primary_key(
        "dim_assets_pkey", "dim_assets", ["user_id", "asset_id"]
    )
    op.create_primary_key(
        "fact_portfolio_snapshots_pkey",
        "fact_portfolio_snapshots",
        ["user_id", "snapshot_date"],
    )
    op.create_index(
        "ix_fact_transactions_user_date",
        "fact_transactions",
        ["user_id", "trans_date"],
    )
    op.create_foreign_key(
        "fact_transactions_user_asset_fkey",
        "fact_transactions",
        "dim_assets",
        ["user_id", "asset_id"],
        ["user_id", "asset_id"],
    )
    op.create_foreign_key(
        "sys_alert_rules_user_asset_fkey",
        "sys_alert_rules",
        "dim_assets",
        ["user_id", "asset_id"],
        ["user_id", "asset_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fact_transactions_user_asset_fkey", "fact_transactions", type_="foreignkey"
    )
    op.drop_constraint(
        "sys_alert_rules_user_asset_fkey", "sys_alert_rules", type_="foreignkey"
    )
    op.drop_index(
        "ix_fact_transactions_user_date", table_name="fact_transactions"
    )
    op.drop_constraint("dim_assets_pkey", "dim_assets", type_="primary")
    op.drop_constraint(
        "fact_portfolio_snapshots_pkey", "fact_portfolio_snapshots", type_="primary"
    )

    op.create_primary_key("dim_assets_pkey", "dim_assets", ["asset_id"])
    op.create_primary_key(
        "fact_portfolio_snapshots_pkey", "fact_portfolio_snapshots", ["snapshot_date"]
    )
    op.create_foreign_key(
        "fact_transactions_asset_id_fkey",
        "fact_transactions",
        "dim_assets",
        ["asset_id"],
        ["asset_id"],
    )
    op.create_foreign_key(
        "sys_alert_rules_asset_id_fkey",
        "sys_alert_rules",
        "dim_assets",
        ["asset_id"],
        ["asset_id"],
    )

    for table in (
        "dim_assets",
        "fact_transactions",
        "fact_portfolio_snapshots",
        "sys_alert_rules",
    ):
        op.drop_column(table, "user_id")

    op.drop_table("user_settings")
    op.drop_table("sys_users")
