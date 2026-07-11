import json
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()

CONFIG_FILENAME = "communication_tools.json"
KEY_FILENAME = "communication_tools.key"


class TelegramTokenPayload(BaseModel):
    token: str


class TelegramStatusResponse(BaseModel):
    configured: bool
    masked_token: str = ""
    storage: str = "backend_encrypted_file"


def _config_path() -> Path:
    return settings.storage_path / CONFIG_FILENAME


def _key_path() -> Path:
    return settings.storage_path / KEY_FILENAME


def _load_or_create_fernet() -> Fernet:
    """Use a stable local encryption key so saved tokens survive backend restarts."""
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        key = path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        path.write_bytes(key)

    return Fernet(key)


def _encrypt_secret(value: str) -> str:
    return _load_or_create_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_secret(value: str) -> str:
    try:
        return _load_or_create_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored Telegram token cannot be decrypted.") from exc


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Communication tools settings file is invalid.",
        ) from exc


def _save_config(data: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _mask_token(token: str) -> str:
    clean = (token or "").strip()
    if not clean:
        return ""
    if len(clean) <= 12:
        return "محفوظ"
    return f"{clean[:6]}...{clean[-4:]}"


def _validate_telegram_token(token: str) -> str:
    clean = (token or "").strip()
    if not clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Telegram token is required.")
    if len(clean) < 20 or ":" not in clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram token format looks invalid. Paste the full bot token from BotFather.",
        )
    return clean


@router.get("/telegram-token/status", response_model=TelegramStatusResponse)
def get_telegram_token_status() -> TelegramStatusResponse:
    data = _load_config()
    encrypted_token = data.get("telegram_bot_token", "")
    if not encrypted_token:
        return TelegramStatusResponse(configured=False)

    try:
        token = _decrypt_secret(encrypted_token)
    except ValueError:
        return TelegramStatusResponse(configured=True, masked_token="محفوظ")

    return TelegramStatusResponse(configured=True, masked_token=_mask_token(token))


@router.put("/telegram-token", response_model=TelegramStatusResponse)
def save_telegram_token(payload: TelegramTokenPayload) -> TelegramStatusResponse:
    token = _validate_telegram_token(payload.token)
    data = _load_config()
    data["telegram_bot_token"] = _encrypt_secret(token)
    data["telegram_bot_token_configured"] = True
    _save_config(data)

    return TelegramStatusResponse(configured=True, masked_token=_mask_token(token))


@router.delete("/telegram-token", response_model=TelegramStatusResponse)
def clear_telegram_token() -> TelegramStatusResponse:
    data = _load_config()
    data.pop("telegram_bot_token", None)
    data["telegram_bot_token_configured"] = False
    _save_config(data)

    return TelegramStatusResponse(configured=False)
