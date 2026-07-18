"""add controlled organization offboarding

Revision ID: f9c4d1a7b253
Revises: e8b3c0f6a142
Create Date: 2026-07-16 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9c4d1a7b253"
down_revision: str | None = "e8b3c0f6a142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_offboarding_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("retention_until", sa.Date(), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_disabled_at", sa.DateTime(), nullable=False),
        sa.Column("deletion_authorized_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_organization_offboarding_cases_organization_id"),
    )
    for column in ("organization_id", "requested_by_user_id", "status"):
        op.create_index(
            f"ix_organization_offboarding_cases_{column}",
            "organization_offboarding_cases",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("status", "requested_by_user_id", "organization_id"):
        op.drop_index(
            f"ix_organization_offboarding_cases_{column}",
            table_name="organization_offboarding_cases",
        )
    op.drop_table("organization_offboarding_cases")
