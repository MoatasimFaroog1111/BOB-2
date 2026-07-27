"""Secure password recovery and invite-only account registration.

Public registration is deliberately unavailable without a signed, short-lived invite.
Password reset responses never disclose whether an account exists.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jwt import PyJWTError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.core import AuditLog, AuthSession, Organization, User
from app.security.audit_chain import utc_naive
from app.security.auth import hash_password, validate_password_strength
from app.security.dependencies import require_permission
from app.security.rate_limiter import get_client_identifier, login_rate_limiter
from app.security.roles import UserRole

logger = logging.getLogger(__name__)
router = APIRouter()

_TOKEN_ALGORITHM = "HS256"
_PASSWORD_RESET_MINUTES = 20
_INVITE_HOURS = 72
_GENERIC_RESET_MESSAGE = (
    "إذا كان البريد مرتبطًا بحساب نشط، فستصلك تعليمات إعادة تعيين كلمة المرور."
)
_ALLOWED_INVITE_ROLES = {
    UserRole.ADMIN,
    UserRole.ACCOUNTANT,
    UserRole.REVIEWER,
    UserRole.AUDITOR,
    UserRole.CFO,
    UserRole.FINANCE_MANAGER,
    UserRole.VIEWER,
}


def _normalized_email(value: str) -> str:
    try:
        result = validate_email(
            value,
            check_deliverability=False,
            test_environment=not settings.is_production,
        )
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return result.normalized.lower()


class PasswordResetRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str) -> str:
        return _normalized_email(value)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=4096)
    new_password: str = Field(..., min_length=12, max_length=128)


class RegistrationRequest(BaseModel):
    invite_token: str = Field(..., min_length=32, max_length=4096)
    email: str
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str) -> str:
        return _normalized_email(value)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Full name is required")
        return normalized


class InvitationRequest(BaseModel):
    email: str
    role: UserRole = UserRole.VIEWER

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str) -> str:
        return _normalized_email(value)


class MessageResponse(BaseModel):
    message: str


class InvitationResponse(BaseModel):
    invite_url: str
    expires_in_hours: int
    email_sent: bool


def _frontend_url(query_name: str, token: str) -> str:
    configured = os.getenv("ACCOUNT_ACCESS_FRONTEND_URL", "").strip()
    base = configured or settings.FRONTEND_ORIGIN.rstrip("/") + "/team"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode({query_name: token})}"


def _password_fingerprint(hashed_password: str) -> str:
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()


def _encode_token(token_type: str, claims: dict[str, object], lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        **claims,
        "type": token_type,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": secrets.token_urlsafe(24),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_TOKEN_ALGORITHM)


def _decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[_TOKEN_ALGORITHM],
            options={
                "require": ["type", "iat", "nbf", "exp", "jti"],
                "verify_signature": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_exp": True,
            },
        )
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الرابط غير صحيح أو انتهت صلاحيته.",
        ) from exc
    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الرابط غير صحيح أو انتهت صلاحيته.",
        )
    return payload


def _send_email(*, recipient: str, subject: str, html_body: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("ACCOUNT_EMAIL_FROM", "").strip()
    if not api_key or not from_email:
        logger.warning("Account-access email delivery is not configured")
        return False

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,
                "to": [recipient],
                "subject": subject,
                "html": html_body,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception("Account-access email delivery failed")
        return False


def _send_password_reset_email(recipient: str, reset_url: str) -> bool:
    safe_url = html.escape(reset_url, quote=True)
    return _send_email(
        recipient=recipient,
        subject="إعادة تعيين كلمة مرور GuardianAI",
        html_body=(
            "<div dir='rtl' style='font-family:Arial,sans-serif'>"
            "<h2>إعادة تعيين كلمة المرور</h2>"
            "<p>تلقينا طلبًا لإعادة تعيين كلمة مرور حسابك في GuardianAI.</p>"
            f"<p><a href='{safe_url}'>اضغط هنا لتعيين كلمة مرور جديدة</a></p>"
            f"<p>تنتهي صلاحية الرابط خلال {_PASSWORD_RESET_MINUTES} دقيقة.</p>"
            "<p>تجاهل الرسالة إذا لم تطلب إعادة التعيين.</p>"
            "</div>"
        ),
    )


def _send_invitation_email(recipient: str, invite_url: str, role: UserRole) -> bool:
    safe_url = html.escape(invite_url, quote=True)
    safe_role = html.escape(role.value)
    return _send_email(
        recipient=recipient,
        subject="دعوة للانضمام إلى GuardianAI",
        html_body=(
            "<div dir='rtl' style='font-family:Arial,sans-serif'>"
            "<h2>دعوة لإنشاء حساب</h2>"
            f"<p>تمت دعوتك إلى GuardianAI بصلاحية <strong>{safe_role}</strong>.</p>"
            f"<p><a href='{safe_url}'>اضغط هنا لإنشاء الحساب</a></p>"
            f"<p>تنتهي صلاحية الرابط خلال {_INVITE_HOURS} ساعة.</p>"
            "</div>"
        ),
    )


def _active_user_and_organization(db: Session, email: str) -> tuple[User | None, Organization | None]:
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or user.organization_id is None:
        return None, None
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == user.organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )
    if not organization:
        return None, None
    return user, organization


@router.post("/password-reset/request", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_id = get_client_identifier(request)
    identifiers = [f"password-reset:ip:{client_id}", f"password-reset:account:{payload.email}"]
    for identifier in identifiers:
        login_rate_limiter.check_rate_limit(identifier)
        login_rate_limiter.record_attempt(identifier, success=False)

    user, organization = _active_user_and_organization(db, payload.email)
    if not user or not organization:
        return MessageResponse(message=_GENERIC_RESET_MESSAGE)

    token = _encode_token(
        "password_reset",
        {
            "uid": user.id,
            "email": user.email,
            "sv": int(user.security_version or 1),
            "pwd": _password_fingerprint(user.hashed_password),
        },
        timedelta(minutes=_PASSWORD_RESET_MINUTES),
    )
    reset_url = _frontend_url("reset_token", token)
    email_sent = _send_password_reset_email(user.email, reset_url)

    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="password_reset_requested",
            entity_type="user_security",
            entity_id=str(user.id),
            ip_address=client_id,
            details={"email_sent": email_sent},
        )
    )
    db.commit()
    return MessageResponse(message=_GENERIC_RESET_MESSAGE)


@router.post("/password-reset/confirm", response_model=MessageResponse)
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    is_valid, error = validate_password_strength(payload.new_password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    token_data = _decode_token(payload.token, "password_reset")
    try:
        user_id = int(token_data.get("uid"))
        security_version = int(token_data.get("sv"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الرابط غير صحيح أو انتهت صلاحيته.",
        ) from exc

    email = str(token_data.get("email") or "").lower()
    fingerprint = str(token_data.get("pwd") or "")
    user = db.query(User).filter(User.id == user_id, User.email == email).first()
    organization = None
    if user and user.organization_id is not None:
        organization = (
            db.query(Organization)
            .filter(Organization.id == user.organization_id, Organization.is_active.is_(True))
            .first()
        )

    if (
        not user
        or not user.is_active
        or not organization
        or int(user.security_version or 1) != security_version
        or not hmac.compare_digest(_password_fingerprint(user.hashed_password), fingerprint)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الرابط غير صحيح أو انتهت صلاحيته.",
        )

    now = utc_naive()
    user.hashed_password = hash_password(payload.new_password)
    user.security_version = int(user.security_version or 1) + 1
    user.security_changed_at = now
    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).update(
        {
            AuthSession.revoked_at: now,
            AuthSession.revocation_reason: "password_reset",
        },
        synchronize_session=False,
    )
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="password_reset_completed",
            entity_type="user_security",
            entity_id=str(user.id),
            ip_address=get_client_identifier(request),
            details={"sessions_revoked": True},
        )
    )
    db.commit()
    return MessageResponse(message="تم تعيين كلمة المرور الجديدة. يمكنك تسجيل الدخول الآن.")


@router.post("/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationRequest,
    request: Request,
    actor: dict = Depends(require_permission("manage_users")),
    db: Session = Depends(get_db),
):
    if payload.role not in _ALLOWED_INVITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لا يمكن إصدار دعوة بهذه الصلاحية.",
        )
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="يوجد حساب مسجل بهذا البريد بالفعل.",
        )

    organization_id = int(actor["organization_id"])
    organization = (
        db.query(Organization)
        .filter(Organization.id == organization_id, Organization.is_active.is_(True))
        .first()
    )
    if not organization:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="المؤسسة غير نشطة.")

    token = _encode_token(
        "user_invitation",
        {
            "email": payload.email,
            "oid": organization_id,
            "role": payload.role.value,
            "iby": int(actor["user_id"]),
        },
        timedelta(hours=_INVITE_HOURS),
    )
    invite_url = _frontend_url("invite", token)
    email_sent = _send_invitation_email(payload.email, invite_url, payload.role)

    db.add(
        AuditLog(
            organization_id=organization_id,
            user_id=int(actor["user_id"]),
            action="user_invitation_created",
            entity_type="user_invitation",
            entity_id=payload.email,
            ip_address=get_client_identifier(request),
            details={"role": payload.role.value, "email_sent": email_sent},
        )
    )
    db.commit()
    return InvitationResponse(
        invite_url=invite_url,
        expires_in_hours=_INVITE_HOURS,
        email_sent=email_sent,
    )


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def register_from_invitation(
    payload: RegistrationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_id = get_client_identifier(request)
    rate_identifier = f"registration:ip:{client_id}"
    login_rate_limiter.check_rate_limit(rate_identifier)

    is_valid, error = validate_password_strength(payload.password)
    if not is_valid:
        login_rate_limiter.record_attempt(rate_identifier, success=False)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    token_data = _decode_token(payload.invite_token, "user_invitation")
    try:
        organization_id = int(token_data.get("oid"))
        inviter_id = int(token_data.get("iby"))
        invited_role = UserRole(str(token_data.get("role")))
    except (TypeError, ValueError) as exc:
        login_rate_limiter.record_attempt(rate_identifier, success=False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الدعوة غير صحيحة أو انتهت صلاحيتها.",
        ) from exc

    invited_email = str(token_data.get("email") or "").lower()
    if (
        invited_role not in _ALLOWED_INVITE_ROLES
        or not hmac.compare_digest(invited_email, payload.email)
    ):
        login_rate_limiter.record_attempt(rate_identifier, success=False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الدعوة لا تطابق بيانات الحساب.",
        )

    organization = (
        db.query(Organization)
        .filter(Organization.id == organization_id, Organization.is_active.is_(True))
        .first()
    )
    inviter = (
        db.query(User)
        .filter(
            User.id == inviter_id,
            User.organization_id == organization_id,
            User.is_active.is_(True),
        )
        .first()
    )
    if not organization or not inviter:
        login_rate_limiter.record_attempt(rate_identifier, success=False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الدعوة غير صحيحة أو انتهت صلاحيتها.",
        )
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="يوجد حساب مسجل بهذا البريد بالفعل.",
        )

    user = User(
        organization_id=organization_id,
        email=payload.email,
        full_name=payload.full_name,
        role=invited_role.value,
        hashed_password=hash_password(payload.password),
        is_active=True,
        security_version=1,
    )
    db.add(user)
    db.flush()
    db.add(
        AuditLog(
            organization_id=organization_id,
            user_id=user.id,
            action="user_registered_from_invitation",
            entity_type="user",
            entity_id=str(user.id),
            ip_address=client_id,
            details={"role": invited_role.value, "invited_by_user_id": inviter_id},
        )
    )
    db.commit()
    login_rate_limiter.record_attempt(rate_identifier, success=True)
    return MessageResponse(message="تم إنشاء الحساب بنجاح. يمكنك تسجيل الدخول الآن.")
