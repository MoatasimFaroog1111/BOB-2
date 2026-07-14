"""add tenant-scoped Telegram identity authorizations

Revision ID: 4c9d7e2a1b60
Revises: 8a2c4e6f7b90
Create Date: 2026-07-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4c9d7e2a1b60"
down_revision: Union[str, Sequence[str], None] = "8a2c4e6f7b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_authorizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("system_user_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("allow_group_chats", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "telegram_user_id > 0",
            name="ck_telegram_authorizations_user_positive",
        ),
        sa.CheckConstraint(
            "telegram_chat_id <> 0",
            name="ck_telegram_authorizations_chat_nonzero",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["system_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "telegram_user_id",
            "telegram_chat_id",
            name="uq_telegram_authorizations_actor_chat",
        ),
    )
    op.create_index(
        "ix_telegram_authorizations_id",
        "telegram_authorizations",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_authorizations_telegram_user_id",
        "telegram_authorizations",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_authorizations_telegram_chat_id",
        "telegram_authorizations",
        ["telegram_chat_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_authorizations_organization_id",
        "telegram_authorizations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_authorizations_system_user_id",
        "telegram_authorizations",
        ["system_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_authorizations_created_by_user_id",
        "telegram_authorizations",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_authorizations_is_active",
        "telegram_authorizations",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_authorizations_is_active",
        table_name="telegram_authorizations",
    )
    op.drop_index(
        "ix_telegram_authorizations_created_by_user_id",
        table_name="telegram_authorizations",
    )
    op.drop_index(
        "ix_telegram_authorizations_system_user_id",
        table_name="telegram_authorizations",
    )
    op.drop_index(
        "ix_telegram_authorizations_organization_id",
        table_name="telegram_authorizations",
    )
    op.drop_index(
        "ix_telegram_authorizations_telegram_chat_id",
        table_name="telegram_authorizations",
    )
    op.drop_index(
        "ix_telegram_authorizations_telegram_user_id",
        table_name="telegram_authorizations",
    )
    op.drop_index(
        "ix_telegram_authorizations_id",
        table_name="telegram_authorizations",
    )
    op.drop_table("telegram_authorizations")
