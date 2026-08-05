"""Email verification tokens — single-use, +24h TTL, HMAC-hashed at rest.

The token is a 32-byte URL-safe random string. Only its HMAC-SHA256
digest (using ``SECRET_KEY`` as the key) is persisted, so a database
leak does not enable account takeover. The raw token is returned to
the caller exactly once (typically embedded in a verification link)
and never recoverable from storage.

Verification rejects:

- Unknown tokens.
- Already-consumed tokens.
- Tokens whose stored expiry has elapsed.

A successful verification marks the token consumed but never deletes
the row — the consumed flag is what blocks reuse. A separate cleanup
job (out of scope for P3) purges old rows.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session


class EmailVerificationError(RuntimeError):
    """Base class for verification failures."""


class EmailVerifier:
    """Issue and verify email-verification tokens."""

    DEFAULT_TTL_HOURS = 24

    def __init__(self, secret_key: str, ttl_hours: int = DEFAULT_TTL_HOURS) -> None:
        if not secret_key:
            raise ValueError("EmailVerifier requires a non-empty secret_key")
        self._key = secret_key.encode("utf-8")
        self._ttl = timedelta(hours=ttl_hours)

    def _hash(self, raw_token: str) -> str:
        return hmac.new(self._key, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()

    def issue(self, *, user_id: int, email: str, db: Session) -> tuple[str, datetime]:
        """Create and persist a new verification token.

        Returns ``(raw_token, expires_at)``. The caller is expected to
        embed ``raw_token`` in a verification link and deliver it to
        the user — the raw value is never recoverable from storage.
        """
        raw = secrets.token_urlsafe(32)
        digest = self._hash(raw)
        expires_at = datetime.now(timezone.utc) + self._ttl

        # Persist in a separate, lightweight table. The schema migration
        # is added as part of P3 (see alembic/versions/P3_add_onboarding.py).
        from app.models.onboarding import EmailVerificationToken  # local import to avoid cycle

        row = EmailVerificationToken(
            user_id=user_id,
            email=email.lower().strip(),
            token_digest=digest,
            expires_at=expires_at,
            consumed_at=None,
        )
        db.add(row)
        db.flush()
        return raw, expires_at

    def verify(self, *, raw_token: str, db: Session) -> int:
        """Verify ``raw_token`` and mark it consumed.

        Returns the verified ``user_id`` on success. Raises
        :class:`EmailVerificationError` on any failure.
        """
        digest = self._hash(raw_token)
        from app.models.onboarding import EmailVerificationToken

        row: Optional[EmailVerificationToken] = (
            db.query(EmailVerificationToken)
            .filter(EmailVerificationToken.token_digest == digest)
            .one_or_none()
        )
        if row is None:
            raise EmailVerificationError("Unknown verification token")
        if row.consumed_at is not None:
            raise EmailVerificationError("Verification token already used")
        expires_at = row.expires_at
        if expires_at is not None:
            # SQLite returns naive datetimes; treat them as UTC. Other
            # backends return tz-aware values. Normalize so the
            # comparison below works in both cases.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                raise EmailVerificationError("Verification token expired")

        row.consumed_at = datetime.now(timezone.utc)
        db.flush()
        return int(row.user_id)


@dataclass(frozen=True)
class IssuedToken:
    raw_token: str
    expires_at: datetime
    email: str


__all__ = ["EmailVerifier", "EmailVerificationError", "IssuedToken"]