import hmac
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jwt import PyJWTError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.core import AuthSession, User
from app.security.auth import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
    new_token_id,
    verify_password,
)
from app.security.dependencies import get_current_token_payload, require_permission
from app.security.rate_limiter import (
    get_client_identifier,
    get_device_identifier,
    login_rate_limiter,
)
from app.security.roles import UserRole, role_has_permission

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


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


def _revoke_family(db: Session, family_id: str) -> None:
    db.query(AuthSession).filter(
        AuthSession.family_id == family_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.utcnow()}, synchronize_session=False)
    db.commit()


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

    if not user.is_active:
        _record_attempts(identifiers, success=False)
        raise _invalid_credentials()

    _record_attempts(identifiers, success=True)

    session_id = new_token_id()
    family_id = new_token_id()
    access_jti = new_token_id()
    refresh_jti = new_token_id()

    access_token = create_access_token(
        subject=user.email,
        role=user.role,
        session_id=session_id,
        jti=access_jti,
    )
    refresh_token = create_refresh_token(
        subject=user.email,
        session_id=session_id,
        family_id=family_id,
        jti=refresh_jti,
    )

    auth_session = AuthSession(
        id=session_id,
        family_id=family_id,
        user_id=user.id,
        access_jti=access_jti,
        refresh_jti=refresh_jti,
        refresh_token_hash=hash_token(refresh_token),
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=get_client_identifier(request),
        user_agent=request.headers.get("User-Agent", "")[:512] or None,
    )
    db.add(auth_session)
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
    if not all([email, session_id, family_id, presented_jti]):
        raise _invalid_refresh()

    auth_session = (
        db.query(AuthSession)
        .filter(
            AuthSession.id == session_id,
            AuthSession.family_id == family_id,
        )
        .first()
    )
    if not auth_session:
        raise _invalid_refresh()

    stored_hash = auth_session.refresh_token_hash
    presented_hash = hash_token(payload.refresh_token)
    token_matches = (
        auth_session.refresh_jti == presented_jti
        and hmac.compare_digest(stored_hash, presented_hash)
    )

    if (
        auth_session.revoked_at is not None
        or auth_session.expires_at <= datetime.utcnow()
        or not token_matches
    ):
        _revoke_family(db, family_id)
        raise _invalid_refresh()

    current_user_agent = request.headers.get("User-Agent", "")[:512] or None
    if auth_session.user_agent and current_user_agent != auth_session.user_agent:
        _revoke_family(db, family_id)
        raise _invalid_refresh()

    user = db.query(User).filter(User.id == auth_session.user_id).first()
    if not user or not user.is_active or user.email != email:
        _revoke_family(db, family_id)
        raise _invalid_refresh()

    new_access_jti = new_token_id()
    new_refresh_jti = new_token_id()
    new_access_token = create_access_token(
        subject=user.email,
        role=user.role,
        session_id=auth_session.id,
        jti=new_access_jti,
    )
    new_refresh_token = create_refresh_token(
        subject=user.email,
        session_id=auth_session.id,
        family_id=auth_session.family_id,
        jti=new_refresh_jti,
    )

    auth_session.access_jti = new_access_jti
    auth_session.refresh_jti = new_refresh_jti
    auth_session.refresh_token_hash = hash_token(new_refresh_token)
    auth_session.last_used_at = datetime.utcnow()
    auth_session.ip_address = get_client_identifier(request)
    auth_session.user_agent = current_user_agent
    db.commit()

    return RefreshTokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/roles")
def list_roles():
    return {
        "roles": [role.value for role in UserRole],
        "note": "Enterprise RBAC foundation is active.",
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
    current_user: dict = Depends(get_current_token_payload),
    db: Session = Depends(get_db),
):
    session_id = current_user.get("sid")
    if session_id:
        auth_session = db.query(AuthSession).filter(AuthSession.id == session_id).first()
        if auth_session and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.utcnow()
            db.commit()

    return {"message": "Logout successful."}
