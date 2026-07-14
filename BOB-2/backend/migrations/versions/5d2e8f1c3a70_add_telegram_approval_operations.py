"""add durable one-time Telegram approval operations

Revision ID: 5d2e8f1c3a70
Revises: 4c9d7e2a1b60
Create Date: 2026-07-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "5d2e8f1c3a70"
down_revision: Union[str, Sequence[str], None] = "4c9d7e2a1b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_approval_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("authorization_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("system_user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("approval_token_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("posted_move_id", sa.BigInteger(), nullable=True),
        sa.Column("attachment_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','processing','posted','cancelled','expired','failed','revoked')",
            name="ck_telegram_approval_operations_status",
        ),
        sa.CheckConstraint(
            "telegram_user_id > 0",
            name="ck_telegram_approval_operations_user_positive",
        ),
        sa.CheckConstraint(
            "telegram_chat_id <> 0",
            name="ck_telegram_approval_operations_chat_nonzero",
        ),
        sa.ForeignKeyConstraint(["authorization_id"], ["telegram_authorizations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["system_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "approval_token_hash",
            name="uq_telegram_approval_operations_token_hash",
        ),
    )
    for column in (
        "id",
        "organization_id",
        "authorization_id",
        "telegram_user_id",
        "telegram_chat_id",
        "system_user_id",
        "status",
        "expires_at",
    ):
        op.create_index(
            f"ix_telegram_approval_operations_{column}",
            "telegram_approval_operations",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in reversed(
        (
            "id",
            "organization_id",
            "authorization_id",
            "telegram_user_id",
            "telegram_chat_id",
            "system_user_id",
            "status",
            "expires_at",
        )
    ):
        op.drop_index(
            f"ix_telegram_approval_operations_{column}",
            table_name="telegram_approval_operations",
        )
    op.drop_table("telegram_approval_operations")
