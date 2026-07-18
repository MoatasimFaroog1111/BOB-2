import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt import PyJWTError

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
MFA_PENDING_EXPIRE_MINUTES = 5


def validate_password_strength(password: str) -> tuple[bool, str]:
    if len(password) < 12:
        return False, "Password must be at least 12 characters long"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-=+\[\]\\/]", password):
        return False, "Password must contain at least one special character"

    common_passwords = {
        "password",
        "123456",
        "qwerty",
        "admin",
        "letmein",
        "owner@seed#2026!",
        "guardian",
    }
    if password.lower() in common_passwords:
        return False, "Password is too common and easily guessable"
    return True, ""


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def new_token_id() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash high-entropy tokens before database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    subject: str,
    role: str,
    expires_delta: timedelta | None = None,
    *,
    session_id: str | None = None,
    jti: str | None = None,
    security_version: int | None = None,
) -> str:
    """Create a signed access token.

    The role claim is retained for client compatibility only. Server authorization
    replaces it with the current database role before evaluating permissions.
    """

    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, object] = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "iat": now,
        "nbf": now,
        "jti": jti or new_token_id(),
        "type": "access",
    }
    if session_id:
        payload["sid"] = session_id
    if security_version is not None:
        payload["sv"] = int(security_version)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    subject: str,
    *,
    session_id: str | None = None,
    family_id: str | None = None,
    jti: str | None = None,
    security_version: int | None = None,
    rotation_generation: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, object] = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "nbf": now,
        "jti": jti or new_token_id(),
        "type": "refresh",
    }
    if session_id:
        payload["sid"] = session_id
    if family_id:
        payload["fid"] = family_id
    if security_version is not None:
        payload["sv"] = int(security_version)
    if rotation_generation is not None:
        payload["rgn"] = int(rotation_generation)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_mfa_pending_token(
    *,
    subject: str,
    role: str,
    user_id: int,
    organization_id: int,
    security_version: int,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "sub": subject,
        "role": role,
        "uid": int(user_id),
        "oid": int(organization_id),
        "sv": int(security_version),
        "exp": now + timedelta(minutes=MFA_PENDING_EXPIRE_MINUTES),
        "iat": now,
        "nbf": now,
        "jti": new_token_id(),
        "type": "mfa_pending",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
            options={
                "require": ["sub", "exp", "iat", "nbf", "jti", "type"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
            },
        )
        if payload.get("type") != expected_type:
            raise PyJWTError("Invalid token type")
        if not isinstance(payload.get("sub"), str) or not payload["sub"]:
            raise PyJWTError("Invalid token subject")
        if not isinstance(payload.get("jti"), str) or not payload["jti"]:
            raise PyJWTError("Invalid token identifier")
        return payload
    except PyJWTError:
        raise
    except Exception as exc:
        raise PyJWTError("Token validation failed") from exc


def decode_access_token(token: str) -> dict:
    return _decode_token(token, "access")


def decode_refresh_token(token: str) -> dict:
    return _decode_token(token, "refresh")


def decode_mfa_pending_token(token: str) -> dict:
    payload = _decode_token(token, "mfa_pending")
    for claim in ("uid", "oid", "sv"):
        try:
            value = int(payload.get(claim))
        except (TypeError, ValueError) as exc:
            raise PyJWTError(f"Invalid {claim} claim") from exc
        if value <= 0:
            raise PyJWTError(f"Invalid {claim} claim")
        payload[claim] = value
    return payload
