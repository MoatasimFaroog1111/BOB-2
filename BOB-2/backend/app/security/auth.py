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
) -> str:
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
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    subject: str,
    *,
    session_id: str | None = None,
    family_id: str | None = None,
    jti: str | None = None,
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
