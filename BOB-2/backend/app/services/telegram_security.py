"""Tenant-aware Telegram identity and permission enforcement.

Every Telegram message and callback must resolve to an active allowlist record, an
active organization, and an active linked system user. Permissions are always read
from the linked user's current role; they are never copied into Telegram state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import AuditLog, Organization, TelegramAuthorization, User
from app.security.roles import role_has_permission


class TelegramAuthorizationDenied(Exception):
    """Safe, structured denial raised before Telegram work is performed."""

    def __init__(self, reason: str, public_message: str = "هذا الحساب غير مصرح له باستخدام البوت."):
        super().__init__(reason)
        self.reason = reason
        self.public_message = public_message


@dataclass(frozen=True, slots=True)
class TelegramSecurityContext:
    authorization_id: int
    telegram_user_id: int
    telegram_chat_id: int
    chat_type: str
    organization_id: int
    system_user_id: int
    system_user_email: str
    system_user_role: str

    def has_permission(self, permission: str) -> bool:
        return role_has_permission(self.system_user_role, permission)

    @property
    def pending_key(self) -> tuple[int, int]:
        """Bind pending work to both the chat and the individual Telegram actor."""
        return (self.telegram_chat_id, self.telegram_user_id)


def _safe_details(details: dict[str, Any] | None) -> dict[str, Any]:
    clean = dict(details or {})
    for key in tuple(clean):
        lowered = key.lower()
        if any(secret_name in lowered for secret_name in ("token", "password", "secret", "authorization")):
            clean[key] = "[REDACTED]"
    return clean


def record_telegram_event(
    db: Session,
    action: str,
    *,
    context: TelegramSecurityContext | None = None,
    organization_id: int | None = None,
    system_user_id: int | None = None,
    telegram_user_id: int | None = None,
    telegram_chat_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Persist a centralized Telegram audit event and fail closed on write failure."""
    if context is not None:
        organization_id = context.organization_id
        system_user_id = context.system_user_id
        telegram_user_id = context.telegram_user_id
        telegram_chat_id = context.telegram_chat_id

    event_details = _safe_details(details)
    event_details.update(
        {
            "telegram_user_id": telegram_user_id,
            "telegram_chat_id": telegram_chat_id,
        }
    )
    audit = AuditLog(
        organization_id=organization_id,
        user_id=system_user_id,
        action=action,
        entity_type="telegram",
        entity_id=(
            f"{telegram_chat_id}:{telegram_user_id}"
            if telegram_chat_id is not None and telegram_user_id is not None
            else None
        ),
        details=event_details,
    )
    try:
        db.add(audit)
        db.commit()
        db.refresh(audit)
    except Exception:
        db.rollback()
        raise TelegramAuthorizationDenied(
            "audit_write_failed",
            "تعذر التحقق الأمني من الطلب. حاول لاحقًا.",
        )
    return audit


def _deny(
    db: Session,
    reason: str,
    *,
    telegram_user_id: int | None,
    telegram_chat_id: int | None,
    event_type: str,
    organization_id: int | None = None,
    system_user_id: int | None = None,
    details: dict[str, Any] | None = None,
    public_message: str = "هذا الحساب غير مصرح له باستخدام البوت.",
) -> None:
    record_telegram_event(
        db,
        "telegram_access_denied",
        organization_id=organization_id,
        system_user_id=system_user_id,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        details={
            "reason": reason,
            "event_type": event_type,
            **(details or {}),
        },
    )
    raise TelegramAuthorizationDenied(reason, public_message)


def authorize_telegram_actor(
    db: Session,
    *,
    telegram_user_id: int | None,
    telegram_chat_id: int | None,
    chat_type: str | None,
    required_permissions: Iterable[str] = (),
    event_type: str,
    update_id: int | None = None,
) -> TelegramSecurityContext:
    """Resolve and authorize one Telegram actor for one concrete event.

    The exact Telegram user/chat pair must be present. Group and supergroup chats need
    both the global opt-in and an allowlist-row opt-in. Channels are never accepted.
    """
    normalized_chat_type = (chat_type or "").strip().lower()
    if not isinstance(telegram_user_id, int) or telegram_user_id <= 0:
        _deny(
            db,
            "missing_or_invalid_telegram_user",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            details={"update_id": update_id},
        )
    if not isinstance(telegram_chat_id, int) or telegram_chat_id == 0:
        _deny(
            db,
            "missing_or_invalid_chat",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            details={"update_id": update_id},
        )
    if normalized_chat_type not in {"private", "group", "supergroup"}:
        _deny(
            db,
            "unsupported_chat_type",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            details={"chat_type": normalized_chat_type, "update_id": update_id},
        )

    authorization = (
        db.query(TelegramAuthorization)
        .filter(
            TelegramAuthorization.telegram_user_id == telegram_user_id,
            TelegramAuthorization.telegram_chat_id == telegram_chat_id,
        )
        .first()
    )
    if authorization is None:
        candidate = (
            db.query(TelegramAuthorization)
            .filter(TelegramAuthorization.telegram_user_id == telegram_user_id)
            .first()
        )
        _deny(
            db,
            "actor_chat_not_allowlisted",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            organization_id=candidate.organization_id if candidate else None,
            system_user_id=candidate.system_user_id if candidate else None,
            details={"chat_type": normalized_chat_type, "update_id": update_id},
        )
    if not authorization.is_active:
        _deny(
            db,
            "authorization_inactive",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            organization_id=authorization.organization_id,
            system_user_id=authorization.system_user_id,
            details={"authorization_id": authorization.id, "update_id": update_id},
        )

    organization = db.query(Organization).filter(Organization.id == authorization.organization_id).first()
    system_user = db.query(User).filter(User.id == authorization.system_user_id).first()
    if organization is None or not organization.is_active:
        _deny(
            db,
            "organization_inactive_or_missing",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            organization_id=authorization.organization_id,
            system_user_id=authorization.system_user_id,
            details={"authorization_id": authorization.id, "update_id": update_id},
        )
    if (
        system_user is None
        or not system_user.is_active
        or system_user.organization_id != authorization.organization_id
    ):
        _deny(
            db,
            "linked_system_user_invalid",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            organization_id=authorization.organization_id,
            system_user_id=authorization.system_user_id,
            details={"authorization_id": authorization.id, "update_id": update_id},
        )

    if normalized_chat_type in {"group", "supergroup"} and not (
        settings.TELEGRAM_ALLOW_GROUP_CHATS and authorization.allow_group_chats
    ):
        _deny(
            db,
            "group_chat_not_allowed",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            organization_id=authorization.organization_id,
            system_user_id=authorization.system_user_id,
            details={
                "authorization_id": authorization.id,
                "chat_type": normalized_chat_type,
                "global_group_opt_in": settings.TELEGRAM_ALLOW_GROUP_CHATS,
                "row_group_opt_in": authorization.allow_group_chats,
                "update_id": update_id,
            },
        )

    missing_permissions = [
        permission
        for permission in required_permissions
        if not role_has_permission(system_user.role, permission)
    ]
    if missing_permissions:
        _deny(
            db,
            "insufficient_system_permissions",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            event_type=event_type,
            organization_id=authorization.organization_id,
            system_user_id=authorization.system_user_id,
            details={
                "authorization_id": authorization.id,
                "required_permissions": list(required_permissions),
                "missing_permissions": missing_permissions,
                "current_role": system_user.role,
                "update_id": update_id,
            },
            public_message="لا يملك مستخدم النظام المرتبط الصلاحية المطلوبة.",
        )

    context = TelegramSecurityContext(
        authorization_id=authorization.id,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        chat_type=normalized_chat_type,
        organization_id=authorization.organization_id,
        system_user_id=system_user.id,
        system_user_email=system_user.email,
        system_user_role=system_user.role,
    )
    authorization.last_used_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise TelegramAuthorizationDenied(
            "authorization_state_update_failed",
            "تعذر التحقق الأمني من الطلب. حاول لاحقًا.",
        )

    record_telegram_event(
        db,
        "telegram_access_granted",
        context=context,
        details={
            "authorization_id": authorization.id,
            "event_type": event_type,
            "chat_type": normalized_chat_type,
            "required_permissions": list(required_permissions),
            "system_role": system_user.role,
            "update_id": update_id,
        },
    )
    return context
