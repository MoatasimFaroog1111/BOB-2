"""Models for the onboarding module.

Currently exposes:

- :class:`EmailVerificationToken` — single-use, +24h TTL token issued
  to a user during self-serve signup. Stored as the HMAC-SHA256 digest
  of the raw token so a database leak does not enable account
  takeover.

The model is intentionally minimal: the only mutable state is
``consumed_at``, which the verifier sets on success. Expiry is checked
at read time rather than via a cron.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class EmailVerificationToken(Base, TimestampMixin):
    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token_digest: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )


__all__ = ["EmailVerificationToken"]