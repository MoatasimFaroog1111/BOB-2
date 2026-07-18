from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jwt import PyJWTError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import LoginResponse
from app.core.config import settings
from app.db.database import get_db
from app.models.core import AuditLog, Organization, User
from app.models.mfa_challenge import MFAChallenge
from app.models.user_mfa import UserMFASetting
from app.security.audit_chain import utc_naive
from app.security.auth import decode_mfa_pending_token, hash_token, verify_password
from app.security.dependencies import get_current_token_payload
from app.security.rate_limiter import (
    get_client_identifier,
    get_device_identifier,
    login_rate_limiter,
)
from app.services.auth_session_issuer import issue_full_session
from app.services.mfa_service import (
    activate_mfa,
    consume_login_code,
    create_pending_totp_secret,
)
from app.services.secret_provider_types import SecretStoreError

router = APIRouter()


class MFASetupRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)


class MFASetupResponse(BaseModel):
    provisioning_uri: str
    manual_entry_secret: str | None = None
    message: str


class MFACodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class MFAVerifyRequest(MFACodeRequest):
    mfa_token: str = Field(..., min_length=64, max_length=4096)


def _current_user(
    db: Session,
    principal: dict,
) -> tuple[User, Organization]:
    user = db.query(User).filter(User.id == principal.get("user_id")).first()
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == (user.organization_id if user else None),
            Organization.is_active.is_(True),
        )
        .first()
    )
    if not user or not user.is_active or not organization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session.")
    return user, organization


@router.post("/mfa/setup", response_model=MFASetupResponse)
def setup_mfa(
    request: Request,
    payload: MFASetupRequest,
    principal: dict = Depends(get_current_token_payload),
    db: Session = Depends(get_db),
):
    user, organization = _current_user(db, principal)
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    try:
        setting, uri = create_pending_totp_secret(
            db,
            organization_id=organization.id,
            user_id=user.id,
            account_name=user.email,
            issuer_name=settings.APP_NAME,
        )
    except (SecretStoreError, ValueError) as exc:
        detail = getattr(exc, "public_message", str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc

    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="mfa_setup_started",
            entity_type="user_security",
            entity_id=str(user.id),
            ip_address=get_client_identifier(request),
            details={"secret_reference_provider": setting.secret_ref.split("://", 1)[0]},
        )
    )
    db.commit()
    return MFASetupResponse(
        provisioning_uri=uri,
        message="Scan the URI in an authenticator app, then activate MFA with the first code.",
    )


@router.post("/mfa/activate")
def activate_mfa_endpoint(
    request: Request,
    payload: MFACodeRequest,
    principal: dict = Depends(get_current_token_payload),
    db: Session = Depends(get_db),
):
    user, organization = _current_user(db, principal)
    setting = (
        db.query(UserMFASetting)
        .filter(
            UserMFASetting.user_id == user.id,
            UserMFASetting.organization_id == organization.id,
        )
        .with_for_update()
        .first()
    )
    if setting is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA setup is required.")
    try:
        activate_mfa(setting, payload.code)
    except (SecretStoreError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="mfa_activated",
            entity_type="user_security",
            entity_id=str(user.id),
            ip_address=get_client_identifier(request),
            details={"sessions_created": False},
        )
    )
    db.commit()
    return {"message": "MFA activated successfully.", "mfa_enabled": True}


@router.post("/mfa/verify", response_model=LoginResponse)
def verify_mfa_login(
    request: Request,
    payload: MFAVerifyRequest,
    db: Session = Depends(get_db),
):
    try:
        token_data = decode_mfa_pending_token(payload.mfa_token)
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA challenge.",
        ) from exc

    challenge = (
        db.query(MFAChallenge)
        .filter(MFAChallenge.jti_hash == hash_token(token_data["jti"]))
        .with_for_update()
        .first()
    )
    now = utc_naive()
    if (
        challenge is None
        or challenge.consumed_at is not None
        or challenge.expires_at <= now
        or challenge.user_id != token_data["uid"]
        or challenge.organization_id != token_data["oid"]
        or challenge.security_version != token_data["sv"]
        or challenge.device_hash != get_device_identifier(request)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA challenge.",
        )

    user = db.query(User).filter(User.id == challenge.user_id).first()
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == challenge.organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )
    setting = (
        db.query(UserMFASetting)
        .filter(
            UserMFASetting.user_id == challenge.user_id,
            UserMFASetting.organization_id == challenge.organization_id,
            UserMFASetting.enabled.is_(True),
        )
        .with_for_update()
        .first()
    )
    if (
        not user
        or not user.is_active
        or not organization
        or not setting
        or user.email != token_data["sub"]
        or int(user.security_version or 1) != token_data["sv"]
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA challenge.",
        )

    limiter_key = f"mfa:{user.email.lower()}:{get_device_identifier(request)}"
    login_rate_limiter.check_rate_limit(limiter_key)
    try:
        consume_login_code(setting, payload.code)
    except (SecretStoreError, ValueError) as exc:
        login_rate_limiter.record_attempt(limiter_key, success=False)
        db.add(
            AuditLog(
                organization_id=organization.id,
                user_id=user.id,
                action="mfa_verification_failed",
                entity_type="user_security",
                entity_id=str(user.id),
                ip_address=get_client_identifier(request),
                details={"reason": "invalid_or_replayed_code"},
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    login_rate_limiter.record_attempt(limiter_key, success=True)
    challenge.consumed_at = now
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="mfa_verification_succeeded",
            entity_type="user_security",
            entity_id=str(user.id),
            ip_address=get_client_identifier(request),
            details={"challenge_consumed": True},
        )
    )
    return LoginResponse(
        **issue_full_session(
            db,
            request=request,
            user=user,
            organization=organization,
        )
    )


@router.get("/mfa/status")
def mfa_status(
    principal: dict = Depends(get_current_token_payload),
    db: Session = Depends(get_db),
):
    user, organization = _current_user(db, principal)
    setting = (
        db.query(UserMFASetting)
        .filter(
            UserMFASetting.user_id == user.id,
            UserMFASetting.organization_id == organization.id,
        )
        .first()
    )
    return {
        "mfa_enabled": bool(setting and setting.enabled),
        "setup_pending": bool(setting and not setting.enabled),
    }
