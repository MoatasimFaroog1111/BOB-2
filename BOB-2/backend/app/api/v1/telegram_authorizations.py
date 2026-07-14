"""Tenant-isolated administration of Telegram identity allowlist records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.core import Organization, TelegramAuthorization, User
from app.security.dependencies import require_permission
from app.security.roles import ROLE_PERMISSIONS, UserRole
from app.services.telegram_accounting_service import revoke_actor_pending_operations
from app.services.telegram_security import record_telegram_event

router = APIRouter()


class TelegramAuthorizationCreate(BaseModel):
    telegram_user_id: int = Field(..., gt=0)
    telegram_chat_id: int
    system_user_id: int = Field(..., gt=0)
    allow_group_chats: bool = False
    is_active: bool = True

    @field_validator("telegram_chat_id")
    @classmethod
    def validate_chat_id(cls, value: int) -> int:
        if value == 0:
            raise ValueError("telegram_chat_id cannot be zero")
        return value


class TelegramAuthorizationUpdate(BaseModel):
    system_user_id: int | None = Field(default=None, gt=0)
    allow_group_chats: bool | None = None
    is_active: bool | None = None


class TelegramSystemUserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    permissions: list[str]


class TelegramAuthorizationResponse(BaseModel):
    id: int
    telegram_user_id: int
    telegram_chat_id: int
    organization_id: int
    system_user_id: int
    system_user_email: str
    system_user_name: str
    system_user_role: str
    created_by_user_id: int
    allow_group_chats: bool
    effective_group_access: bool
    is_active: bool
    last_used_at: str | None
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


def _active_organization(db: Session, organization_id: int) -> Organization:
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if organization is None or not organization.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated organization is inactive.",
        )
    return organization


def _target_user(db: Session, organization_id: int, system_user_id: int) -> User:
    user = (
        db.query(User)
        .filter(
            User.id == system_user_id,
            User.organization_id == organization_id,
        )
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The linked system user was not found in this organization.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The linked system user is inactive.",
        )
    return user


def _validate_group_policy(telegram_chat_id: int, allow_group_chats: bool) -> None:
    if telegram_chat_id < 0 and not allow_group_chats:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Negative Telegram chat IDs are group chats and require explicit row opt-in.",
        )
    if allow_group_chats and not settings.TELEGRAM_ALLOW_GROUP_CHATS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telegram group chats are globally disabled.",
        )


def _row_for_tenant(db: Session, authorization_id: int, organization_id: int) -> TelegramAuthorization:
    row = (
        db.query(TelegramAuthorization)
        .filter(
            TelegramAuthorization.id == authorization_id,
            TelegramAuthorization.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Authorization not found.")
    return row


def _serialize(db: Session, row: TelegramAuthorization) -> TelegramAuthorizationResponse:
    linked_user = db.query(User).filter(User.id == row.system_user_id).first()
    return TelegramAuthorizationResponse(
        id=row.id,
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        organization_id=row.organization_id,
        system_user_id=row.system_user_id,
        system_user_email=linked_user.email if linked_user else "",
        system_user_name=linked_user.full_name if linked_user else "",
        system_user_role=linked_user.role if linked_user else "inactive_or_missing",
        created_by_user_id=row.created_by_user_id,
        allow_group_chats=row.allow_group_chats,
        effective_group_access=(settings.TELEGRAM_ALLOW_GROUP_CHATS and row.allow_group_chats),
        is_active=row.is_active,
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _clear_runtime_marker(telegram_chat_id: int, telegram_user_id: int) -> int:
    from app.services import telegram_bot

    with telegram_bot.pending_entries_lock:
        return 1 if telegram_bot.PENDING_ENTRIES.pop((telegram_chat_id, telegram_user_id), None) else 0


def _revoke_pending_for_row(db: Session, row: TelegramAuthorization, reason: str) -> int:
    """Use the request's tenant transaction; never open a second database session."""
    durable = revoke_actor_pending_operations(
        db,
        telegram_chat_id=row.telegram_chat_id,
        telegram_user_id=row.telegram_user_id,
        reason=reason,
    )
    local = _clear_runtime_marker(row.telegram_chat_id, row.telegram_user_id)
    return max(durable, local)


@router.get("/system-users", response_model=list[TelegramSystemUserResponse])
def list_telegram_system_users(
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> list[TelegramSystemUserResponse]:
    organization_id = _organization_id(current_user)
    _active_organization(db, organization_id)
    users = (
        db.query(User)
        .filter(User.organization_id == organization_id, User.is_active.is_(True))
        .order_by(User.full_name.asc(), User.id.asc())
        .all()
    )
    result: list[TelegramSystemUserResponse] = []
    for user in users:
        try:
            role = UserRole(user.role)
            permissions = list(ROLE_PERMISSIONS.get(role, []))
        except ValueError:
            permissions = []
        result.append(
            TelegramSystemUserResponse(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                permissions=permissions,
            )
        )
    return result


@router.get("/authorizations", response_model=list[TelegramAuthorizationResponse])
def list_telegram_authorizations(
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> list[TelegramAuthorizationResponse]:
    organization_id = _organization_id(current_user)
    _active_organization(db, organization_id)
    rows = (
        db.query(TelegramAuthorization)
        .filter(TelegramAuthorization.organization_id == organization_id)
        .order_by(TelegramAuthorization.id.asc())
        .all()
    )
    return [_serialize(db, row) for row in rows]


@router.post(
    "/authorizations",
    response_model=TelegramAuthorizationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_telegram_authorization(
    payload: TelegramAuthorizationCreate,
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> TelegramAuthorizationResponse:
    organization_id = _organization_id(current_user)
    _active_organization(db, organization_id)
    target_user = _target_user(db, organization_id, payload.system_user_id)
    _validate_group_policy(payload.telegram_chat_id, payload.allow_group_chats)

    duplicate = (
        db.query(TelegramAuthorization)
        .filter(
            TelegramAuthorization.telegram_user_id == payload.telegram_user_id,
            TelegramAuthorization.telegram_chat_id == payload.telegram_chat_id,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Telegram user/chat pair is already registered.",
        )

    creator_id = current_user.get("user_id")
    if not isinstance(creator_id, int):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user session.")

    row = TelegramAuthorization(
        telegram_user_id=payload.telegram_user_id,
        telegram_chat_id=payload.telegram_chat_id,
        organization_id=organization_id,
        system_user_id=target_user.id,
        created_by_user_id=creator_id,
        allow_group_chats=payload.allow_group_chats,
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_telegram_event(
        db,
        "telegram_authorization_created",
        organization_id=organization_id,
        system_user_id=creator_id,
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        details={
            "authorization_record_id": row.id,
            "linked_system_user_id": row.system_user_id,
            "allow_group_chats": row.allow_group_chats,
            "is_active": row.is_active,
        },
    )
    return _serialize(db, row)


@router.patch("/authorizations/{authorization_id}", response_model=TelegramAuthorizationResponse)
def update_telegram_authorization(
    authorization_id: int,
    payload: TelegramAuthorizationUpdate,
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> TelegramAuthorizationResponse:
    organization_id = _organization_id(current_user)
    _active_organization(db, organization_id)
    row = _row_for_tenant(db, authorization_id, organization_id)
    before = {
        "system_user_id": row.system_user_id,
        "allow_group_chats": row.allow_group_chats,
        "is_active": row.is_active,
    }

    if payload.system_user_id is not None:
        row.system_user_id = _target_user(db, organization_id, payload.system_user_id).id
    if payload.allow_group_chats is not None:
        _validate_group_policy(row.telegram_chat_id, payload.allow_group_chats)
        row.allow_group_chats = payload.allow_group_chats
    if payload.is_active is not None:
        if payload.is_active:
            _target_user(db, organization_id, row.system_user_id)
        row.is_active = payload.is_active

    security_binding_changed = (
        not row.is_active or before["system_user_id"] != row.system_user_id
    )
    cleared = (
        _revoke_pending_for_row(db, row, "authorization_binding_changed")
        if security_binding_changed
        else 0
    )
    if not security_binding_changed:
        db.commit()
    db.refresh(row)

    actor_id = current_user.get("user_id")
    record_telegram_event(
        db,
        "telegram_authorization_updated",
        organization_id=organization_id,
        system_user_id=actor_id if isinstance(actor_id, int) else None,
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        details={
            "authorization_record_id": row.id,
            "before": before,
            "after": {
                "system_user_id": row.system_user_id,
                "allow_group_chats": row.allow_group_chats,
                "is_active": row.is_active,
            },
            "pending_approvals_revoked": cleared,
        },
    )
    return _serialize(db, row)


@router.delete("/authorizations/{authorization_id}", response_model=TelegramAuthorizationResponse)
def deactivate_telegram_authorization(
    authorization_id: int,
    current_user: dict = Depends(require_permission("manage_settings")),
    db: Session = Depends(get_db),
) -> TelegramAuthorizationResponse:
    organization_id = _organization_id(current_user)
    _active_organization(db, organization_id)
    row = _row_for_tenant(db, authorization_id, organization_id)
    row.is_active = False
    cleared = _revoke_pending_for_row(db, row, "authorization_deactivated")
    db.refresh(row)

    actor_id = current_user.get("user_id")
    record_telegram_event(
        db,
        "telegram_authorization_deactivated",
        organization_id=organization_id,
        system_user_id=actor_id if isinstance(actor_id, int) else None,
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        details={
            "authorization_record_id": row.id,
            "linked_system_user_id": row.system_user_id,
            "pending_entries_cleared": cleared,
        },
    )
    return _serialize(db, row)
