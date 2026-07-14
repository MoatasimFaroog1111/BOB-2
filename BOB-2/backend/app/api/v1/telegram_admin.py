"""Administrative Telegram runtime controls.

These endpoints intentionally expose runtime state only.  They never return the bot
token or any decrypted secret.  Re-enabling after an emergency stop is deliberately
not exposed until the remaining authorization and approval hardening is complete.
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.core import AuditLog
from app.security.dependencies import require_permission
from app.services.telegram_runtime import (
    emergency_disable_telegram_bot,
    get_runtime_status,
)

router = APIRouter()


def _record_admin_event(
    db: Session,
    current_user: dict,
    action: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            organization_id=current_user.get("organization_id"),
            user_id=current_user.get("user_id"),
            action=action,
            entity_type="telegram_runtime",
            entity_id="singleton",
            details=details,
        )
    )
    db.commit()


@router.get("/runtime-status")
def telegram_runtime_status(
    current_user: dict = Depends(require_permission("manage_settings")),
) -> dict[str, Any]:
    """Return secret-free Telegram runtime status to authorized administrators."""
    status = get_runtime_status()
    status["requested_by"] = current_user.get("sub")
    return status


@router.post("/emergency-disable")
def emergency_disable(
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Stop polling immediately and clear every in-memory pending approval."""
    before = get_runtime_status()
    after = emergency_disable_telegram_bot()
    _record_admin_event(
        db,
        current_user,
        "telegram_bot_emergency_disabled",
        {
            "was_running": before["running"],
            "pending_entries_cleared": before["pending_entries"],
            "policy_reason": after["policy_reason"],
        },
    )
    after["requested_by"] = current_user.get("sub")
    return after
