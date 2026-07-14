from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="Saudi Arabia", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuthSession(Base, TimestampMixin):
    """Server-side session state for access/refresh token revocation and rotation."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    family_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    access_jti: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    refresh_jti: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ERPConnection(Base, TimestampMixin):
    __tablename__ = "erp_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_secret_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(100), default="uploaded", nullable=False)
    classification: Mapped[str | None] = mapped_column(String(100), nullable=True)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(100), default="pending", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtractedFinancialObject(Base, TimestampMixin):
    __tablename__ = "extracted_financial_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence_score: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extracted_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(100), default="pending_validation", nullable=False)


class JournalEntryRecord(Base, TimestampMixin):
    """Tenant-isolated, durable journal entry snapshot."""

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    reference: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    memo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    lines: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    total_debit: Mapped[float] = mapped_column(Float, nullable=False)
    total_credit: Mapped[float] = mapped_column(Float, nullable=False)


class VectorRecord(Base, TimestampMixin):
    """Tenant-isolated embedding storage without an exposed vector database server."""

    __tablename__ = "vector_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "collection_name",
            "document_key",
            name="uq_vector_records_tenant_collection_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    collection_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    document_key: Mapped[str] = mapped_column(String(128), nullable=False)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    record_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
