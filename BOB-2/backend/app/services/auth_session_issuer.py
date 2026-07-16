from __future__ import annotations

from datetime import timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import AuthSession, Organization, User
from app.security.audit_chain import utc_naive
from app.security.auth import (
    create_access_token,
    create_refresh_token,
    hash_token,
    new_token_id,
)
from app.security.rate_limiter import get_client_identifier
from app.services.refresh_token_rotation import create_rotation_state, record_session_event


def issue_full_session(
    db: Session,
    *,
    request: Request,
    user: User,
    organization: Organization,
) -> dict[str, object]:
    security_version = int(user.security_version or 1)
    session_id = new_token_id()
    family_id = new_token_id()
    access_jti = new_token_id()
    refresh_jti = new_token_id()
    request_ip = get_client_identifier(request)
    request_user_agent = request.headers.get("User-Agent", "")[:512] or None

    access_token = create_access_token(
        subject=user.email,
        role=user.role,
        session_id=session_id,
        jti=access_jti,
        security_version=security_version,
    )
    refresh_token = create_refresh_token(
        subject=user.email,
        session_id=session_id,
        family_id=family_id,
        jti=refresh_jti,
        security_version=security_version,
        rotation_generation=0,
    )

    db.add(
        AuthSession(
            id=session_id,
            family_id=family_id,
            user_id=user.id,
            organization_id=organization.id,
            user_security_version=security_version,
            access_jti=access_jti,
            refresh_jti=refresh_jti,
            refresh_token_hash=hash_token(refresh_token),
            expires_at=utc_naive()
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            ip_address=request_ip,
            user_agent=request_user_agent,
        )
    )
    create_rotation_state(db, session_id=session_id, family_id=family_id)
    record_session_event(
        db,
        event_type="session_created",
        outcome="success",
        organization_id=organization.id,
        user_id=user.id,
        session_id=session_id,
        family_id=family_id,
        generation=0,
        ip_address=request_ip,
        user_agent=request_user_agent,
    )
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "role": user.role,
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "mfa_required": False,
        "mfa_token": None,
    }
