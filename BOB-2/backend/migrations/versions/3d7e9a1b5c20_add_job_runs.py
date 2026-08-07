"""add tenant-scoped asynchronous job runs

Revision ID: 3d7e9a1b5c20
Revises: f9c4d1a7b253
Create Date: 2026-07-28 14:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3d7e9a1b5c20"
down_revision: str | None = "f9c4d1a7b253"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_job_runs_progress_range",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_job_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_job_runs_organization_id",
        "job_runs",
        ["organization_id"],
        unique=False,
    )
    op.create_index("ix_job_runs_kind", "job_runs", ["kind"], unique=False)
    op.create_index("ix_job_runs_status", "job_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_runs_status", table_name="job_runs")
    op.drop_index("ix_job_runs_kind", table_name="job_runs")
    op.drop_index("ix_job_runs_organization_id", table_name="job_runs")
    op.drop_table("job_runs")
