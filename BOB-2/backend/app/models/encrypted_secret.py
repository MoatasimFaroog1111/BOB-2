from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class EncryptedSecretVersion(Base, TimestampMixin):
    """AES-256-GCM ciphertext with authenticated tenant and version metadata."""

    __tablename__ = "encrypted_secret_versions"
    __table_args__ = (
        UniqueConstraint(
            "secret_name",
            "version",
            name="uq_encrypted_secret_versions_name_version",
        ),
        CheckConstraint(
            "status IN ('active','disabled')",
            name="ck_encrypted_secret_versions_status",
        ),
        CheckConstraint(
            "key_version > 0",
            name="ck_encrypted_secret_versions_key_version_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    secret_name: Mapped[str] = mapped_column(String(127), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    organization_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    authenticated_tags: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
