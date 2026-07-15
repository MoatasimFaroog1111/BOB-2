import hmac
from datetime import datetime, timedelta

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jwt import PyJWTError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.core import AuditLog, AuthSession, Organization, User
from app.models.session_security import AuthSessionRotationState
from app.security.auth import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    new_token_id,
    validate_password_strength,
    verify_password,
)
from app.security.dependencies import get_current_token_payload, require_permission
from app.security.rate_limiter import (
    get_client_identifier,
    get_device_identifier,
    login_rate_limiter,
)
from app.security.roles import UserRole, role_has_permission
from app.services.refresh_token_rotation import (
    claim_refresh_generation,
    create_rotation_state,
    load_rotation_state_for_update,
    record_session_event,
    revoke_family,
)

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str) -> str:
        try:
            normalized = validate_email(
                value,
                check_deliverability=False,
                test_environment=True,
            )
        except EmailNotValidError as exc:
            raise ValueError(str(exc)) from exc
        return normalized.normalized


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=32, max_length=4096)


class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)


class ChangePasswordResponse(BaseModel):
    message: str
    sessions_revoked: bool = True


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _invalid_refresh() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _auth_limit_identifiers(request: Request, email: str) -> list[str]:
    ip = get_client_identifier(request)
    device = get_device_identifier(request)
    normalized_email = email.lower()
    return [
        f"ip:{ip}",
        f"account:{normalized_email}",
        f"account-device:{normalized_email}:{device}",
    ]


def _record_attempts(identifiers: list[str], success: bool) -> None:
    for identifier in identifiers:
        login_rate_limiter.record_attempt(identifier, success=success)


def _active_organization(db: Session, organization_id: int | None) -> Organization | None:
    if organization_id is None:
        return None
    return (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    identifiers = _auth_limit_identifiers(request, payload.email)
    for identifier in identifiers:
        login_rate_limiter.check_rate_limit(identifier)

    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        _record_attempts(identifiers, success=False)
        raise _invalid_credentials()

    organization = _active_organization(db, user.organization_id)
    if not user.is_active or not organization:
        _record_attempts(identifiers, success=False)
        raise _invalid_credentials()

    _record_attempts(identifiers, success=True)

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

    auth_session = AuthSession(
        id=session_id,
        family_id=family_id,
        user_id=user.id,
        organization_id=organization.id,
        user_security_version=security_version,
        access_jti=access_jti,
        refresh_jti=refresh_jti,
        refresh_token_hash=hash_token(refresh_token),
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=request_ip,
        user_agent=request_user_agent,
    )
    db.add(auth_session)
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

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user.role,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
def refresh_access_token(
    request: Request,
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    try:
        token_data = decode_refresh_token(payload.refresh_token)
    except PyJWTError:
        raise _invalid_refresh()

    email = token_data.get("sub")
    session_id = token_data.get("sid")
    family_id = token_data.get("fid")
    presented_jti = token_data.get("jti")
    try:
        token_security_version = int(token_data.get("sv"))
        presented_generation = int(token_data.get("rgn"))
    except (TypeError, ValueError):
        token_security_version = -1
        presented_generation = -1
    if (
        not all([email, session_id, family_id, presented_jti])
        or token_security_version < 1
        or presented_generation < 0
    ):
        raise _invalid_refresh()

    request_ip = get_client_identifier(request)
    current_user_agent = request.headers.get("User-Agent", "")[:512] or None
    presented_hash = hash_token(payload.refresh_token)

    rotation_state = load_rotation_state_for_update(
        db,
        session_id=session_id,
        family_id=family_id,
    )
    auth_session = db.execute(
        select(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.family_id == family_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if not auth_session or not rotation_state:
        db.rollback()
        raise _invalid_refresh()

    session_context = {
        "organization_id": auth_session.organization_id,
        "user_id": auth_session.user_id,
        "session_id": auth_session.id,
        "family_id": auth_session.family_id,
    }
    token_matches = (
        rotation_state.generation == presented_generation
        and auth_session.refresh_jti == presented_jti
        and hmac.compare_digest(auth_session.refresh_token_hash, presented_hash)
    )

    if (
        auth_session.revoked_at is not None
        or auth_session.expires_at <= datetime.utcnow()
        or not token_matches
    ):
        db.rollback()
        revoke_family(
            db,
            family_id=family_id,
            reason="refresh_replay_or_expiry",
            event_type="refresh_replay_detected",
            generation=presented_generation,
            ip_address=request_ip,
            user_agent=current_user_agent,
            metadata={"cause": "token_state_mismatch"},
            **session_context,
        )
        raise _invalid_refresh()

    if auth_session.user_agent and current_user_agent != auth_session.user_agent:
        db.rollback()
        revoke_family(
            db,
            family_id=family_id,
            reason="refresh_device_changed",
            event_type="refresh_device_changed",
            generation=presented_generation,
            ip_address=request_ip,
            user_agent=current_user_agent,
            **session_context,
        )
        raise _invalid_refresh()

    user = db.query(User).filter(User.id == auth_session.user_id).first()
    organization = _active_organization(db, user.organization_id if user else None)
    current_security_version = int(user.security_version or 1) if user else -1
    if (
        not user
        or not user.is_active
        or user.email != email
        or not organization
        or auth_session.organization_id != user.organization_id
        or auth_session.user_security_version != current_security_version
        or token_security_version != current_security_version
    ):
        db.rollback()
        revoke_family(
            db,
            family_id=family_id,
            reason="user_security_state_changed",
            event_type="refresh_security_state_changed",
            generation=presented_generation,
            ip_address=request_ip,
            user_agent=current_user_agent,
            **session_context,
        )
        raise _invalid_refresh()

    now = datetime.utcnow()
    new_generation = presented_generation + 1
    new_access_jti = new_token_id()
    new_refresh_jti = new_token_id()
    new_access_token = create_access_token(
        subject=user.email,
        role=user.role,
        session_id=auth_session.id,
        jti=new_access_jti,
        security_version=current_security_version,
    )
    new_refresh_token = create_refresh_token(
        subject=user.email,
        session_id=auth_session.id,
        family_id=auth_session.family_id,
        jti=new_refresh_jti,
        security_version=current_security_version,
        rotation_generation=new_generation,
    )

    if not claim_refresh_generation(
        db,
        session_id=session_id,
        family_id=family_id,
        expected_generation=presented_generation,
        rotated_at=now,
    ):
        db.rollback()
        revoke_family(
            db,
            family_id=family_id,
            reason="concurrent_refresh_replay",
            event_type="concurrent_refresh_replay",
            generation=presented_generation,
            ip_address=request_ip,
            user_agent=current_user_agent,
            **session_context,
        )
        raise _invalid_refresh()

    auth_session.access_jti = new_access_jti
    auth_session.refresh_jti = new_refresh_jti
    auth_session.refresh_token_hash = hash_token(new_refresh_token)
    auth_session.last_used_at = now
    auth_session.ip_address = request_ip
    auth_session.user_agent = current_user_agent
    record_session_event(
        db,
        event_type="refresh_rotated",
        outcome="success",
        generation=new_generation,
        ip_address=request_ip,
        user_agent=current_user_agent,
        **session_context,
    )
    db.commit()

    return RefreshTokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_principal: dict = Depends(get_current_token_payload),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == current_principal.get("user_id")).first()
    if not user or not user.is_active:
        raise _invalid_credentials()
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    valid, message = validate_password_strength(payload.new_password)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    if verify_password(payload.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password.",
        )

    user.hashed_password = hash_password(payload.new_password)
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action="password_changed",
            entity_type="user_security",
            entity_id=str(user.id),
            ip_address=request.client.host if request.client else None,
            details={"sessions_revoked": True},
        )
    )
    db.commit()

    return ChangePasswordResponse(
        message="Password changed successfully. Sign in again on all devices.",
    )


@router.get("/roles")
def list_roles(
    current_user: dict = Depends(require_permission("manage_users")),
):
    return {
        "roles": [role.value for role in UserRole],
        "note": "Enterprise RBAC foundation is active.",
        "requested_by": current_user.get("sub"),
    }


@router.get("/check-permission/{permission}")
def check_permission(
    permission: str,
    current_user: dict = Depends(require_permission("manage_users")),
):
    return {
        "requested_permission": permission,
        "current_role": current_user.get("role"),
        "allowed": role_has_permission(current_user.get("role"), permission),
    }


@router.post("/logout")
def logout(
    request: Request,
    current_user: dict = Depends(get_current_token_payload),
    db: Session = Depends(get_db),
):
    session_id = current_user.get("sid")
    if session_id:
        auth_session = db.query(AuthSession).filter(AuthSession.id == session_id).first()
        if auth_session and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.utcnow()
            auth_session.revocation_reason = "user_logout"
            rotation_state = db.query(AuthSessionRotationState).filter(
                AuthSessionRotationState.session_id == session_id
            ).first()
            record_session_event(
                db,
                event_type="user_logout",
                outcome="success",
                organization_id=auth_session.organization_id,
                user_id=auth_session.user_id,
                session_id=auth_session.id,
                family_id=auth_session.family_id,
                generation=rotation_state.generation if rotation_state else None,
                ip_address=get_client_identifier(request),
                user_agent=request.headers.get("User-Agent", "")[:512] or None,
            )
            db.commit()

    return {"message": "Logout successful."}
