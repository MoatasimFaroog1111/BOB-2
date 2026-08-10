"""Telegram configuration HTTP component retained for API compatibility."""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class TelegramConfigRequest(BaseModel):
    token: str
    is_active: bool = True


@router.get("/telegram-config")
def get_telegram_config():
    import urllib.request

    from app.services.telegram_bot import get_telegram_token

    token = get_telegram_token()
    config_path = settings.storage_path / "telegram_config.json"

    is_active = False
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            is_active = config.get("is_active", False)
        except Exception:
            pass

    if not token:
        return {"token": "", "is_active": is_active, "bot_info": None}

    bot_info = None
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=5) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            if res_data.get("ok"):
                bot_info = {
                    "username": res_data["result"].get("username"),
                    "first_name": res_data["result"].get("first_name"),
                }
    except Exception as e:
        logger.info(f"[Telegram Config] Failed to fetch getMe: {e}")

    # Mask the token for the frontend (only show first 10 chars)
    masked_token = token[:10] + "..." if len(token) > 10 else token

    return {
        "token": masked_token,
        "is_active": is_active,
        "bot_info": bot_info,
    }


@router.post("/telegram-config")
def save_telegram_config(payload: TelegramConfigRequest):
    import urllib.request
    from pathlib import Path
    
    token = payload.token.strip()
    if token:
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            with urllib.request.urlopen(url, timeout=10) as res:
                res_data = json.loads(res.read().decode("utf-8"))
                if not res_data.get("ok"):
                    raise Exception("Invalid token response")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Telegram Bot Token: {str(e)}")
            
    from app.services.telegram_bot import save_telegram_config as bot_save_config
    from app.services.telegram_bot import start_telegram_bot, stop_telegram_bot

    is_active = payload.is_active if token else False
    if not bot_save_config(token, is_active):
        raise HTTPException(status_code=500, detail="Failed to save Telegram configuration.")

    stop_telegram_bot()
    if is_active:
        start_telegram_bot()

    return {"status": "success", "message": "Telegram configuration saved successfully."}
