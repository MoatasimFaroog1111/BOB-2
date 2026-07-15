from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.dependencies import require_permission
from app.services.secret_store import (
    SecretStoreError,
    binding_status,
    put_tenant_secret,
    revoke_tenant_secret,
)

router = APIRouter()


class TelegramTokenPayload(BaseModel):
    token: str


class TelegramStatusResponse(BaseModel):
    configured: bool
    storage: str = "central_secret_store"
    provider: str | None = None
    status: str | None = None
    version_fingerprint: str | None = None
    last_rotated_at: datetime | None = None


def _tenant(current_user: dict) -> tuple[int, int]:
    organization_id = current_user.get("organization_id")
    user_id = current_user.get("user_id")
    if not isinstance(organization_id, int) or organization_id <= 0:
        raise HTTPException(status_code=403, detail="The authenticated user has no active organization.")
    if not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(status_code=401, detail="The authenticated user identity is incomplete.")
    return organization_id, user_id


def _validate_telegram_token(token: str) -> str:
    clean = (token or "").strip()
    if not clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Telegram token is required.")
    if len(clean) < 20 or len(clean) > 256 or ":" not in clean:
        raise HTTPException(status_code=400, detail="Telegram token format is invalid.")
    return clean


def _response(binding) -> TelegramStatusResponse:
    if binding is None:
        return TelegramStatusResponse(configured=False)
    return TelegramStatusResponse(
        configured=binding.status == "active" and binding.revoked_at is None,
        provider=binding.provider,
        status=binding.status,
        version_fingerprint=binding.fingerprint_sha256[:12],
        last_rotated_at=binding.last_rotated_at,
    )


@router.get("/telegram-token/status", response_model=TelegramStatusResponse)
def get_telegram_token_status(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("manage_settings")),
) -> TelegramStatusResponse:
    organization_id, _ = _tenant(current_user)
    return _response(
        binding_status(db, organization_id=organization_id, purpose="telegram_bot_token")
    )


@router.put("/telegram-token", response_model=TelegramStatusResponse)
def save_telegram_token(
    payload: TelegramTokenPayload,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("manage_settings")),
) -> TelegramStatusResponse:
    organization_id, user_id = _tenant(current_user)
    try:
        binding = put_tenant_secret(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            purpose="telegram_bot_token",
            value=_validate_telegram_token(payload.token),
        )
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=exc.public_message) from exc
    return _response(binding)


@router.delete("/telegram-token", response_model=TelegramStatusResponse)
def clear_telegram_token(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("manage_settings")),
) -> TelegramStatusResponse:
    organization_id, user_id = _tenant(current_user)
    try:
        revoke_tenant_secret(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            purpose="telegram_bot_token",
        )
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=exc.public_message) from exc
    return TelegramStatusResponse(configured=False)
