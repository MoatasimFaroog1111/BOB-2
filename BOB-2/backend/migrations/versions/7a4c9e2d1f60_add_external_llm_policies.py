"""add tenant-scoped external LLM consent policies

Revision ID: 7a4c9e2d1f60
Revises: 5d2e8f1c3a70
Create Date: 2026-07-14 12:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7a4c9e2d1f60"
down_revision: str | None = "5d2e8f1c3a70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_llm_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("external_llm_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_provider", sa.String(length=100), nullable=True),
        sa.Column("approved_model", sa.String(length=200), nullable=True),
        sa.Column("allowed_purposes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("allow_redacted_document_text", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_financial_values", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_redacted_text_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dpa_version", sa.String(length=100), nullable=True),
        sa.Column("dpa_reference", sa.String(length=255), nullable=True),
        sa.Column("data_residency_region", sa.String(length=100), nullable=True),
        sa.Column("provider_retention_mode", sa.String(length=100), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("policy_version > 0", name="ck_external_llm_policy_version_positive"),
        sa.CheckConstraint(
            "max_redacted_text_chars >= 0 AND max_redacted_text_chars <= 8000",
            name="ck_external_llm_policy_text_limit",
        ),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_external_llm_policies_organization"),
    )
    op.create_index(
        op.f("ix_external_llm_policies_id"),
        "external_llm_policies",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_llm_policies_organization_id"),
        "external_llm_policies",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_llm_policies_accepted_by_user_id"),
        "external_llm_policies",
        ["accepted_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_llm_policies_revoked_by_user_id"),
        "external_llm_policies",
        ["revoked_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_external_llm_policies_revoked_by_user_id"), table_name="external_llm_policies")
    op.drop_index(op.f("ix_external_llm_policies_accepted_by_user_id"), table_name="external_llm_policies")
    op.drop_index(op.f("ix_external_llm_policies_organization_id"), table_name="external_llm_policies")
    op.drop_index(op.f("ix_external_llm_policies_id"), table_name="external_llm_policies")
    op.drop_table("external_llm_policies")
