"""convert persisted monetary float columns to fixed-point numeric

Revision ID: e6b8c1d4a290
Revises: 9c7f2a4b1d80
Create Date: 2026-07-15 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6b8c1d4a290"
down_revision: str | None = "9c7f2a4b1d80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY_TYPE = sa.Numeric(precision=20, scale=2)


def _validate_and_normalize_existing_journals() -> None:
    connection = op.get_bind()
    invalid = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM journal_entries
            WHERE ROUND(CAST(total_debit AS NUMERIC(20, 6)), 2) <= 0
               OR ROUND(CAST(total_credit AS NUMERIC(20, 6)), 2) <= 0
               OR ROUND(CAST(total_debit AS NUMERIC(20, 6)), 2)
                  <> ROUND(CAST(total_credit AS NUMERIC(20, 6)), 2)
            """
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError(
            "Cannot migrate journal monetary columns: existing entries contain "
            "non-positive or unbalanced totals after two-decimal normalization."
        )

    connection.execute(
        sa.text(
            """
            UPDATE journal_entries
               SET total_debit = ROUND(CAST(total_debit AS NUMERIC(20, 6)), 2),
                   total_credit = ROUND(CAST(total_credit AS NUMERIC(20, 6)), 2)
            """
        )
    )


def upgrade() -> None:
    _validate_and_normalize_existing_journals()

    with op.batch_alter_table("journal_entries") as batch_op:
        batch_op.alter_column(
            "total_debit",
            existing_type=sa.Float(),
            type_=MONEY_TYPE,
            existing_nullable=False,
        )
        batch_op.alter_column(
            "total_credit",
            existing_type=sa.Float(),
            type_=MONEY_TYPE,
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_journal_entries_positive_total",
            "total_debit > 0",
        )
        batch_op.create_check_constraint(
            "ck_journal_entries_balanced_totals",
            "total_debit = total_credit",
        )

    with op.batch_alter_table("bank_reconciliation_audit_logs") as batch_op:
        batch_op.alter_column(
            "statement_total",
            existing_type=sa.Float(),
            type_=MONEY_TYPE,
            existing_nullable=True,
        )
        batch_op.alter_column(
            "ledger_total",
            existing_type=sa.Float(),
            type_=MONEY_TYPE,
            existing_nullable=True,
        )
        batch_op.alter_column(
            "difference",
            existing_type=sa.Float(),
            type_=MONEY_TYPE,
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("bank_reconciliation_audit_logs") as batch_op:
        batch_op.alter_column(
            "difference",
            existing_type=MONEY_TYPE,
            type_=sa.Float(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "ledger_total",
            existing_type=MONEY_TYPE,
            type_=sa.Float(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "statement_total",
            existing_type=MONEY_TYPE,
            type_=sa.Float(),
            existing_nullable=True,
        )

    with op.batch_alter_table("journal_entries") as batch_op:
        batch_op.drop_constraint(
            "ck_journal_entries_balanced_totals",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_journal_entries_positive_total",
            type_="check",
        )
        batch_op.alter_column(
            "total_credit",
            existing_type=MONEY_TYPE,
            type_=sa.Float(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "total_debit",
            existing_type=MONEY_TYPE,
            type_=sa.Float(),
            existing_nullable=False,
        )
