"""add versioned BOB bank rules

Revision ID: a2d6c8e1f740
Revises: f9c4d1a7b253
Create Date: 2026-08-12 16:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2d6c8e1f740"
down_revision: str | None = "f9c4d1a7b253"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_system", sa.String(length=50), nullable=False, server_default="bob"),
        sa.Column("source_external_id", sa.String(length=200), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("retired_by_user_id", sa.Integer(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("priority >= 0 AND priority <= 100000", name="ck_bank_rules_priority"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["retired_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "journal_id",
            "company_id",
            "name",
            name="uq_bank_rules_org_journal_company_name",
        ),
    )
    op.create_index("ix_bank_rules_id", "bank_rules", ["id"], unique=False)
    op.create_index("ix_bank_rules_organization_id", "bank_rules", ["organization_id"], unique=False)
    op.create_index("ix_bank_rules_journal_id", "bank_rules", ["journal_id"], unique=False)
    op.create_index("ix_bank_rules_company_id", "bank_rules", ["company_id"], unique=False)
    op.create_index("ix_bank_rules_is_enabled", "bank_rules", ["is_enabled"], unique=False)

    op.create_table(
        "bank_rule_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bank_rule_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("version_number > 0", name="ck_bank_rule_version_positive"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["bank_rule_id"], ["bank_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_rule_id", "version_number", name="uq_bank_rule_version_number"),
    )
    op.create_index("ix_bank_rule_versions_id", "bank_rule_versions", ["id"], unique=False)
    op.create_index("ix_bank_rule_versions_bank_rule_id", "bank_rule_versions", ["bank_rule_id"], unique=False)
    op.create_index("ix_bank_rule_versions_approval_status", "bank_rule_versions", ["approval_status"], unique=False)
    op.create_index("ix_bank_rule_versions_fingerprint", "bank_rule_versions", ["fingerprint"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bank_rule_versions_fingerprint", table_name="bank_rule_versions")
    op.drop_index("ix_bank_rule_versions_approval_status", table_name="bank_rule_versions")
    op.drop_index("ix_bank_rule_versions_bank_rule_id", table_name="bank_rule_versions")
    op.drop_index("ix_bank_rule_versions_id", table_name="bank_rule_versions")
    op.drop_table("bank_rule_versions")
    op.drop_index("ix_bank_rules_is_enabled", table_name="bank_rules")
    op.drop_index("ix_bank_rules_company_id", table_name="bank_rules")
    op.drop_index("ix_bank_rules_journal_id", table_name="bank_rules")
    op.drop_index("ix_bank_rules_organization_id", table_name="bank_rules")
    op.drop_index("ix_bank_rules_id", table_name="bank_rules")
    op.drop_table("bank_rules")
