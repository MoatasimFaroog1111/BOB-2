"""Administrative visibility and revocation for durable Telegram approvals."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.core import TelegramApprovalOperation
from app.security.dependencies import require_permission
from app.services.telegram_security import record_telegram_event

router = APIRouter()

_ALLOWED_STATUSES = {
    "pending",
    "processing",
    "posted",
    "cancelled",
    "expired",
    "failed",
    "revoked",
}


class TelegramApprovalResponse(BaseModel):
    id: int
    organization_id: int
    authorization_id: int
    telegram_user_id: int
    telegram_chat_id: int
    system_user_id: int
    source: str
    status: str
    content_hash_prefix: str
    filename: str
    document_class: str
    amount: float
    expires_at: str
    consumed_at: str | None
    revoked_at: str | None
    failure_code: str | None
    posted_move_id: int | None
    attachment_id: int | None
    created_at: str
    updated_at: str


def _organization_id(current_user: dict) -> int:
    value = current_user.get("organization_id")
    if not isinstance(value, int) or value <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not assigned to an organization.",
        )
    return value


def _serialize(row: TelegramApprovalOperation) -> TelegramApprovalResponse:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return TelegramApprovalResponse(
        id=row.id,
        organization_id=row.organization_id,
        authorization_id=row.authorization_id,
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        system_user_id=row.system_user_id,
        source=row.source,
        status=row.status,
        content_hash_prefix=row.content_hash[:12],
        filename=str(payload.get("filename") or ""),
        document_class=str(payload.get("document_class") or ""),
        amount=float(payload.get("amount") or 0.0),
        expires_at=row.expires_at.isoformat(),
        consumed_at=row.consumed_at.isoformat() if row.consumed_at else None,
        revoked_at=row.revoked_at.isoformat() if row.revoked_at else None,
        failure_code=row.failure_code,
        posted_move_id=row.posted_move_id,
        attachment_id=row.attachment_id,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/approval-operations", response_model=list[TelegramApprovalResponse])
def list_approval_operations(
    operation_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> list[TelegramApprovalResponse]:
    organization_id = _organization_id(current_user)
    query = db.query(TelegramApprovalOperation).filter(
        TelegramApprovalOperation.organization_id == organization_id
    )
    if operation_status is not None:
        if operation_status not in _ALLOWED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unsupported approval status.",
            )
        query = query.filter(TelegramApprovalOperation.status == operation_status)
    rows = query.order_by(TelegramApprovalOperation.id.desc()).limit(limit).all()
    return [_serialize(row) for row in rows]


@router.post(
    "/approval-operations/{operation_id}/revoke",
    response_model=TelegramApprovalResponse,
)
def revoke_approval_operation(
    operation_id: int,
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> TelegramApprovalResponse:
    organization_id = _organization_id(current_user)
    row = (
        db.query(TelegramApprovalOperation)
        .filter(
            TelegramApprovalOperation.id == operation_id,
            TelegramApprovalOperation.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval operation not found.")
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending approval operations can be revoked.",
        )
    now = datetime.utcnow()
    updated = (
        db.query(TelegramApprovalOperation)
        .filter(
            TelegramApprovalOperation.id == row.id,
            TelegramApprovalOperation.organization_id == organization_id,
            TelegramApprovalOperation.status == "pending",
        )
        .update(
            {
                "status": "revoked",
                "revoked_at": now,
                "failure_code": "revoked_by_administrator",
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval state changed before revocation completed.",
        )
    row = db.query(TelegramApprovalOperation).filter(TelegramApprovalOperation.id == operation_id).first()
    actor_id = current_user.get("user_id")
    record_telegram_event(
        db,
        "telegram_approval_revoked_by_administrator",
        organization_id=organization_id,
        system_user_id=actor_id if isinstance(actor_id, int) else None,
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        details={"operation_id": row.id, "authorization_id": row.authorization_id},
    )
    return _serialize(row)
