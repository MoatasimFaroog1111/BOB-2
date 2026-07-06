"""add bank reconciliation audit logs

Revision ID: e2b5a8c9d104
Revises: 9b7c1e4a2d31
Create Date: 2026-07-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e2b5a8c9d104"
down_revision: Union[str, Sequence[str], None] = "9b7c1e4a2d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_reconciliation_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("bank_journal_id", sa.Integer(), nullable=True),
        sa.Column("bank_journal_name", sa.String(length=255), nullable=True),
        sa.Column("statement_filename", sa.String(length=500), nullable=True),
        sa.Column("statement_file_hash", sa.String(length=64), nullable=True),
        sa.Column("statement_file_size", sa.Integer(), nullable=True),
        sa.Column("date_from", sa.String(length=20), nullable=True),
        sa.Column("date_to", sa.String(length=20), nullable=True),
        sa.Column("statement_total", sa.Float(), nullable=True),
        sa.Column("ledger_total", sa.Float(), nullable=True),
        sa.Column("difference", sa.Float(), nullable=True),
        sa.Column("statement_count", sa.Integer(), nullable=True),
        sa.Column("ledger_count", sa.Integer(), nullable=True),
        sa.Column("matched_count", sa.Integer(), nullable=True),
        sa.Column("smart_matched_count", sa.Integer(), nullable=True),
        sa.Column("statement_only_count", sa.Integer(), nullable=True),
        sa.Column("ledger_only_count", sa.Integer(), nullable=True),
        sa.Column("odoo_raw_count", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="generated"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bank_reconciliation_audit_logs_id"), "bank_reconciliation_audit_logs", ["id"], unique=False)
    op.create_index(op.f("ix_bank_reconciliation_audit_logs_organization_id"), "bank_reconciliation_audit_logs", ["organization_id"], unique=False)
    op.create_index(op.f("ix_bank_reconciliation_audit_logs_company_id"), "bank_reconciliation_audit_logs", ["company_id"], unique=False)
    op.create_index(op.f("ix_bank_reconciliation_audit_logs_bank_journal_id"), "bank_reconciliation_audit_logs", ["bank_journal_id"], unique=False)
    op.create_index(op.f("ix_bank_reconciliation_audit_logs_statement_file_hash"), "bank_reconciliation_audit_logs", ["statement_file_hash"], unique=False)
    op.create_index(op.f("ix_bank_reconciliation_audit_logs_status"), "bank_reconciliation_audit_logs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("bank_reconciliation_audit_logs")
