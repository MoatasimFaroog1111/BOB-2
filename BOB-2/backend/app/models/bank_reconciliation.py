from decimal import Decimal

from sqlalchemy import Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class BankReconciliationAuditLog(Base, TimestampMixin):
    """Immutable audit evidence for each bank reconciliation run.

    The record stores totals, counts, selected Odoo bank journal metadata, a
    SHA-256 hash of the uploaded statement, and the generated report payload.
    It intentionally stores no ERP credentials and does not represent an ERP
    posting instruction.
    """

    __tablename__ = "bank_reconciliation_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bank_journal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bank_journal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    statement_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statement_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    statement_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    statement_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    ledger_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    difference: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    statement_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ledger_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smart_matched_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statement_only_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ledger_only_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odoo_raw_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="generated", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
