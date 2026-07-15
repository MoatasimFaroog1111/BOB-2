from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class TenantSecretBinding(Base, TimestampMixin):
    """Current secret reference for one purpose inside one organization.

    Secret values are never persisted in this database. ``secret_name`` and
    ``current_version`` point to the configured remote secret provider.
    """

    __tablename__ = "tenant_secret_bindings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "purpose",
            name="uq_tenant_secret_bindings_organization_purpose",
        ),
        CheckConstraint(
            "status IN ('active','revoked')",
            name="ck_tenant_secret_bindings_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    secret_name: Mapped[str] = mapped_column(String(127), nullable=False)
    current_version: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    rotated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    last_rotated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TenantSecretVersion(Base, TimestampMixin):
    """Append-only metadata for a remote secret version."""

    __tablename__ = "tenant_secret_versions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "secret_name",
            "version",
            name="uq_tenant_secret_versions_remote_version",
        ),
        CheckConstraint(
            "status IN ('active','superseded','revoked')",
            name="ck_tenant_secret_versions_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    binding_id: Mapped[int] = mapped_column(
        ForeignKey("tenant_secret_bindings.id"), index=True, nullable=False
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    secret_name: Mapped[str] = mapped_column(String(127), nullable=False)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
