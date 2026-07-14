"""Expiry cleanup for durable Telegram approvals and their retained files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.core import AuditLog, TelegramApprovalOperation


def expire_pending_approvals(
    db: Session,
    *,
    now: datetime | None = None,
) -> list[int]:
    """Atomically expire overdue approvals, audit them, and remove retained files.

    The database transition is committed before any filesystem deletion. A failed file
    deletion therefore cannot make an expired approval usable again.
    """

    effective_now = now or datetime.utcnow()
    rows = (
        db.query(TelegramApprovalOperation)
        .filter(
            TelegramApprovalOperation.status == "pending",
            TelegramApprovalOperation.expires_at <= effective_now,
        )
        .order_by(TelegramApprovalOperation.id.asc())
        .all()
    )
    if not rows:
        return []

    expired_ids: list[int] = []
    file_paths: list[str] = []
    for row in rows:
        row.status = "expired"
        row.consumed_at = effective_now
        row.failure_code = "approval_expired_background_cleanup"
        expired_ids.append(row.id)
        if row.file_path:
            file_paths.append(row.file_path)
        db.add(
            AuditLog(
                organization_id=row.organization_id,
                user_id=row.system_user_id,
                action="telegram_approval_expired_background",
                entity_type="telegram",
                entity_id=f"{row.telegram_chat_id}:{row.telegram_user_id}",
                details={
                    "telegram_user_id": row.telegram_user_id,
                    "telegram_chat_id": row.telegram_chat_id,
                    "operation_id": row.id,
                    "authorization_id": "[REDACTED]",
                    "expired_at": effective_now.isoformat(),
                },
            )
        )

    db.commit()

    for file_path in file_paths:
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            # The database state is authoritative. A later maintenance pass may remove
            # any filesystem residue, but the approval remains unusable.
            continue
    return expired_ids
