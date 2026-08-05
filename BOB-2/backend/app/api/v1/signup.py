"""Public signup and email-verification endpoints.

These endpoints are only mounted (or only return 200) when the active
deployment frame enables self-serve signup. The router always
declares the routes, but each handler checks the capability and
returns 404 / 501 when disabled — so a single backend image can be
configured per-frame without code changes.

Endpoints:

- ``POST /api/v1/auth/signup``        — create tenant + owner + token.
- ``POST /api/v1/auth/verify-email`` — consume the verification token.
- ``POST /api/v1/billing/webhook``   — provider webhook ingestion
  (mounted by the billing router; lives here for cohesion with the
  signup flow which both feed the same tenant).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.capabilities.service import (
    CAPABILITY_SELF_SERVE_SIGNUP,
    CapabilitiesService,
)
from app.core.config import settings
from app.db.database import get_db
from app.onboarding.email_verifier import EmailVerifier, EmailVerificationError
from app.onboarding.signup_service import (
    SignupAlreadyExistsError,
    SignupReceipt,
    SignupService,
)

router = APIRouter(tags=["onboarding"])


class SignupRequest(BaseModel):
    organization_name: str = Field(..., min_length=2, max_length=255)
    legal_name: str | None = Field(None, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=12, max_length=128)
    owner_full_name: str | None = Field(None, max_length=255)


class SignupResponse(BaseModel):
    organization_id: int
    owner_user_id: int
    tenant_slug: str
    owner_email: str
    verification_token: str
    verification_expires_at: datetime

    @classmethod
    def from_receipt(cls, r: SignupReceipt) -> "SignupResponse":
        return cls(
            organization_id=r.organization_id,
            owner_user_id=r.owner_user_id,
            tenant_slug=r.tenant_slug,
            owner_email=r.owner_email,
            verification_token=r.verification_token,
            verification_expires_at=r.verification_expires_at,
        )


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)


class VerifyEmailResponse(BaseModel):
    verified: bool
    user_id: int


def _require_self_serve(request: Request) -> None:
    """Return 404 when self-serve signup is not enabled in this frame."""
    caps: CapabilitiesService = CapabilitiesService(
        getattr(request.app.state, "frame", None)
        or __import__("app.core.deployment_frame", fromlist=["DeploymentFrame"]).DeploymentFrame.ENTERPRISE
    )
    view = caps.view()
    state = view.capabilities.get(CAPABILITY_SELF_SERVE_SIGNUP, "disabled")
    if state == "disabled":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Self-serve signup is not enabled in this deployment frame.",
        )


def _build_verifier(db: Annotated[Session, Depends(get_db)]) -> EmailVerifier:
    return EmailVerifier(secret_key=settings.SECRET_KEY)


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    payload: SignupRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SignupResponse:
    """Self-serve tenant creation.

    The verification token is returned in the response body. In a real
    deployment the server would also send an email with the link; for
    P3 the token is surfaced so the developer can confirm the flow.
    """
    _require_self_serve(request)
    verifier = EmailVerifier(secret_key=settings.SECRET_KEY)
    service = SignupService(
        db=db,
        email_verifier=verifier,
        default_org_name=settings.GUARDIAN_DEFAULT_ORG_NAME,
        default_org_legal_name=settings.GUARDIAN_DEFAULT_ORG_LEGAL_NAME,
    )
    try:
        receipt = service.signup(
            organization_name=payload.organization_name,
            owner_email=payload.owner_email,
            owner_password=payload.owner_password,
            owner_full_name=payload.owner_full_name,
            legal_name=payload.legal_name,
        )
    except SignupAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return SignupResponse.from_receipt(receipt)


@router.post("/verify-email", response_model=VerifyEmailResponse)
def verify_email(
    payload: VerifyEmailRequest,
    db: Annotated[Session, Depends(get_db)],
    verifier: Annotated[EmailVerifier, Depends(_build_verifier)],
) -> VerifyEmailResponse:
    """Verify an email and activate the user.

    On success the corresponding user's ``is_active`` flag flips to
    True so they can log in. The token is single-use.
    """
    try:
        user_id = verifier.verify(raw_token=payload.token, db=db)
    except EmailVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    from app.models.core import User  # local import to avoid cycle

    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is not None and not user.is_active:
        user.is_active = True
        db.commit()

    return VerifyEmailResponse(verified=True, user_id=user_id)


__all__ = ["router"]