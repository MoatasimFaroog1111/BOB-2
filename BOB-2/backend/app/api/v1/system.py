from __future__ import annotations

import hmac
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.core import AuditLog, AuthSession, Document, Organization, User
from app.models.organization_offboarding import OrganizationOffboardingCase
from app.models.tenant_secret import TenantSecretBinding, TenantSecretVersion
from app.security.audit_chain import utc_naive
from app.security.dependencies import require_permission
from app.services.audit_integrity import verify_tenant_audit_chain

router = APIRouter()


class OrganizationOffboardingRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)
    retention_until: date | None = None
    legal_hold: bool = False

    @model_validator(mode="after")
    def validate_retention(self):
        if not self.legal_hold:
            if self.retention_until is None:
                raise ValueError("retention_until is required unless legal_hold is active")
            if self.retention_until <= date.today():
                raise ValueError("retention_until must be in the future")
        return self


@router.get("/status")
def system_status(
    current_user: dict = Depends(require_permission("manage_settings")),
):
    """Return detailed runtime status only to authorized administrators."""
    return {
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "status": "running",
        "api_version": "v1",
        "guardrails": "enabled",
        "human_approval": "required_for_financial_posting",
        "requested_by": current_user.get("sub"),
    }


@router.get("/audit-integrity")
def audit_integrity(
    current_user: dict = Depends(require_permission("view_audit_logs")),
    db: Session = Depends(get_db),
):
    """Recalculate the authenticated tenant's audit chain without disclosing events."""
    organization_id = current_user.get("organization_id")
    if not isinstance(organization_id, int) or organization_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated organization context is required.",
        )
    return verify_tenant_audit_chain(db, organization_id)


def _require_owner_for_organization(
    db: Session,
    *,
    current_user: dict,
    organization_id: int,
) -> tuple[User, Organization]:
    if current_user.get("role") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization owner may start offboarding.",
        )
    if current_user.get("organization_id") != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )
    user = db.query(User).filter(User.id == current_user.get("user_id")).first()
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if (
        user is None
        or user.organization_id != organization_id
        or not user.is_active
        or organization is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )
    return user, organization


@router.post("/organization/{organization_id}/offboarding")
def start_organization_offboarding(
    organization_id: int,
    payload: OrganizationOffboardingRequest,
    confirmation_name: str = Header(..., alias="X-Confirm-Organization-Name"),
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
):
    """Disable tenant access and place its records under controlled retention.

    This endpoint deliberately does not physically delete financial or audit data.
    Destruction requires a later documented retention/legal decision and must never
    bypass statutory accounting, tax, dispute or audit duties.
    """
    user, organization = _require_owner_for_organization(
        db,
        current_user=current_user,
        organization_id=organization_id,
    )
    if not hmac.compare_digest(confirmation_name.strip(), organization.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization-name confirmation did not match.",
        )

    existing = (
        db.query(OrganizationOffboardingCase)
        .filter(OrganizationOffboardingCase.organization_id == organization_id)
        .with_for_update()
        .first()
    )
    if existing is not None:
        return {
            "organization_id": organization_id,
            "status": existing.status,
            "retention_until": existing.retention_until,
            "legal_hold": existing.legal_hold,
            "access_disabled": not organization.is_active,
        }

    now = utc_naive()
    organization.is_active = False
    db.query(AuthSession).filter(
        AuthSession.organization_id == organization_id,
        AuthSession.revoked_at.is_(None),
    ).update(
        {
            AuthSession.revoked_at: now,
            AuthSession.revocation_reason: "organization_offboarding",
        },
        synchronize_session=False,
    )
    db.query(Document).filter(Document.organization_id == organization_id).update(
        {Document.status: "retention_hold"},
        synchronize_session=False,
    )

    bindings = (
        db.query(TenantSecretBinding)
        .filter(TenantSecretBinding.organization_id == organization_id)
        .all()
    )
    binding_ids = []
    for binding in bindings:
        binding_ids.append(binding.id)
        binding.status = "revoked"
        binding.revoked_by_user_id = user.id
        binding.revoked_at = now
    if binding_ids:
        db.query(TenantSecretVersion).filter(
            TenantSecretVersion.binding_id.in_(binding_ids),
            TenantSecretVersion.status != "revoked",
        ).update(
            {
                TenantSecretVersion.status: "revoked",
                TenantSecretVersion.revoked_at: now,
            },
            synchronize_session=False,
        )

    offboarding = OrganizationOffboardingCase(
        organization_id=organization_id,
        requested_by_user_id=user.id,
        status="legal_hold" if payload.legal_hold else "retention_hold",
        reason=payload.reason,
        retention_until=payload.retention_until,
        legal_hold=payload.legal_hold,
        access_disabled_at=now,
    )
    db.add(offboarding)
    db.add(
        AuditLog(
            organization_id=organization_id,
            user_id=user.id,
            action="organization_offboarding_started",
            entity_type="organization",
            entity_id=str(organization_id),
            details={
                "status": offboarding.status,
                "retention_until": (
                    payload.retention_until.isoformat()
                    if payload.retention_until
                    else None
                ),
                "legal_hold": payload.legal_hold,
                "sessions_revoked": True,
                "documents_status": "retention_hold",
                "secret_bindings_revoked": len(bindings),
                "physical_deletion_performed": False,
            },
        )
    )
    db.commit()
    return {
        "organization_id": organization_id,
        "status": offboarding.status,
        "retention_until": offboarding.retention_until,
        "legal_hold": offboarding.legal_hold,
        "access_disabled": True,
        "physical_deletion_performed": False,
    }


@router.get("/organization/{organization_id}/offboarding")
def get_organization_offboarding(
    organization_id: int,
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
):
    _require_owner_for_organization(
        db,
        current_user=current_user,
        organization_id=organization_id,
    )
    case = (
        db.query(OrganizationOffboardingCase)
        .filter(OrganizationOffboardingCase.organization_id == organization_id)
        .first()
    )
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offboarding not started.")
    return {
        "organization_id": organization_id,
        "status": case.status,
        "retention_until": case.retention_until,
        "legal_hold": case.legal_hold,
        "access_disabled_at": case.access_disabled_at,
        "physical_deletion_performed": False,
    }
