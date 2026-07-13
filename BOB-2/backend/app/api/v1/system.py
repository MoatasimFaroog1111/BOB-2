from fastapi import APIRouter, Depends

from app.core.config import settings
from app.security.dependencies import require_permission

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
