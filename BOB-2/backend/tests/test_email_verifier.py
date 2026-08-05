"""Tests for the email verification token model + verifier."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.onboarding.email_verifier import (
    EmailVerificationError,
    EmailVerifier,
)


def test_verifier_requires_secret_key() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        EmailVerifier(secret_key="")


def test_issue_and_verify_round_trip(db) -> None:
    """Issue a token, immediately verify it, mark consumed."""
    verifier = EmailVerifier(secret_key="unit-test-secret-key-must-be-long")

    # Need a user row for the FK
    from app.models.core import Organization, User
    from app.security.auth import hash_password

    org = Organization(name="Test Org", legal_name="Test Org", country="SA")
    db.add(org)
    db.flush()
    user = User(
        organization_id=org.id,
        email="verify-test@guardian-ai.com",
        full_name="Verify Test",
        role="owner",
        hashed_password=hash_password("Test@Pass1234!"),
        is_active=False,
    )
    db.add(user)
    db.commit()

    raw_token, expires_at = verifier.issue(
        user_id=user.id, email=user.email, db=db
    )
    assert len(raw_token) >= 30
    assert expires_at > datetime.now(timezone.utc)

    verified_user_id = verifier.verify(raw_token=raw_token, db=db)
    assert verified_user_id == user.id

    # Second verify must fail (single-use)
    with pytest.raises(EmailVerificationError, match="already used"):
        verifier.verify(raw_token=raw_token, db=db)


def test_verify_rejects_unknown_token(db) -> None:
    verifier = EmailVerifier(secret_key="another-secret-key-for-tests-12345")
    with pytest.raises(EmailVerificationError, match="Unknown"):
        verifier.verify(raw_token="this-is-fake", db=db)


def test_verify_rejects_expired_token(db) -> None:
    """Manually back-date a token's expiry, then verify should reject."""
    from app.models.core import Organization, User
    from app.models.onboarding import EmailVerificationToken
    from app.security.auth import hash_password

    org = Organization(name="Expire Org", legal_name="Expire Org", country="SA")
    db.add(org)
    db.flush()
    user = User(
        organization_id=org.id,
        email="expire-test@guardian-ai.com",
        full_name="Expire Test",
        role="owner",
        hashed_password=hash_password("Test@Pass1234!"),
        is_active=False,
    )
    db.add(user)
    db.flush()

    verifier = EmailVerifier(secret_key="expiry-test-secret-key-1234567890")
    raw_token, _ = verifier.issue(user_id=user.id, email=user.email, db=db)

    # Backdate the row to before now
    row = (
        db.query(EmailVerificationToken)
        .filter(EmailVerificationToken.user_id == user.id)
        .one()
    )
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    with pytest.raises(EmailVerificationError, match="expired"):
        verifier.verify(raw_token=raw_token, db=db)