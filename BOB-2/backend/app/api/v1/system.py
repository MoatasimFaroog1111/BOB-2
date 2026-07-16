from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.security.dependencies import require_permission
from app.services.audit_integrity import verify_tenant_audit_chain

router = APIRouter()


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
