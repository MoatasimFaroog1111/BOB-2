"""add per-user MFA settings

Revision ID: d7a2b9e5f031
Revises: c6f1a8d4e920
Create Date: 2026-07-16 17:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a2b9e5f031"
down_revision: str | None = "c6f1a8d4e920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_mfa_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("secret_ref", sa.String(length=500), nullable=False),
        sa.Column("last_accepted_counter", sa.BigInteger(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_mfa_settings_user_id"),
    )
    op.create_index(
        "ix_user_mfa_settings_user_id",
        "user_mfa_settings",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_mfa_settings_organization_id",
        "user_mfa_settings",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_mfa_settings_organization_id",
        table_name="user_mfa_settings",
    )
    op.drop_index(
        "ix_user_mfa_settings_user_id",
        table_name="user_mfa_settings",
    )
    op.drop_table("user_mfa_settings")
