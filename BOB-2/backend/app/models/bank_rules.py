from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BankRule(Base, TimestampMixin):
    """Tenant-owned bank classification rule.

    Odoo IDs stored here are references only. BOB owns the rule lifecycle/versioning,
    while Odoo remains the source of truth for journals, accounts, partners, and
    analytic accounts.
    """

    __tablename__ = "bank_rules"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "journal_id",
            "company_id",
            "name",
            name="uq_bank_rules_org_journal_company_name",
        ),
        CheckConstraint("priority >= 0 AND priority <= 100000", name="ck_bank_rules_priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    journal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False, default="bob")
    source_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    retired_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BankRuleVersion(Base):
    """Immutable version snapshot for a BankRule.

    Editing never mutates an approved version. A new draft version is created and only
    becomes executable after an explicit approval that also validates its Odoo
    references.
    """

    __tablename__ = "bank_rule_versions"
    __table_args__ = (
        UniqueConstraint("bank_rule_id", "version_number", name="uq_bank_rule_version_number"),
        CheckConstraint("version_number > 0", name="ck_bank_rule_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bank_rule_id: Mapped[int] = mapped_column(
        ForeignKey("bank_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    conditions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    target: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now_naive)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
