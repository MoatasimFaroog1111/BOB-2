"""add one-time MFA challenges

Revision ID: e8b3c0f6a142
Revises: d7a2b9e5f031
Create Date: 2026-07-16 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b3c0f6a142"
down_revision: str | None = "d7a2b9e5f031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mfa_challenges",
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column("device_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("jti_hash"),
    )
    for column in ("user_id", "organization_id", "expires_at", "consumed_at"):
        op.create_index(
            f"ix_mfa_challenges_{column}",
            "mfa_challenges",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("consumed_at", "expires_at", "organization_id", "user_id"):
        op.drop_index(f"ix_mfa_challenges_{column}", table_name="mfa_challenges")
    op.drop_table("mfa_challenges")
