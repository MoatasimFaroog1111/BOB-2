from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class ExternalLLMPolicy(Base, TimestampMixin):
    """Tenant-scoped legal and technical authorization for external LLM disclosure.

    API keys and prompts are intentionally not stored here. A configured provider key is
    only a technical credential; this row is the separate organizational authorization.
    """

    __tablename__ = "external_llm_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_external_llm_policies_organization"),
        CheckConstraint("policy_version > 0", name="ck_external_llm_policy_version_positive"),
        CheckConstraint(
            "max_redacted_text_chars >= 0 AND max_redacted_text_chars <= 8000",
            name="ck_external_llm_policy_text_limit",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    external_llm_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    allowed_purposes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allow_redacted_document_text: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    allow_financial_values: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_redacted_text_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dpa_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dpa_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_residency_region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_retention_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
