"""Telegram bot compatibility facade over the bounded ingestion pipeline.

No document downloader or parser lives here. Polling is delegated to the fixed-worker
pipeline in ``telegram_ingestion``. Historical direct-processing entry points fail
closed so older imports cannot recreate thread-per-upload or unbounded-download paths.
"""

from __future__ import annotations

import html
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.db.database import SessionLocal
from app.security.encryption import decrypt_value, encrypt_value
from app.services.telegram_accounting_service import (
    TelegramApprovalDenied,
    cancel_approval,
    consume_and_post_approval,
    parse_callback_data,
    revoke_actor_pending_operations,
)
from app.services.telegram_ingestion import (
    TelegramIngestionDenied,
    secure_polling_loop,
    shutdown_ingestion_queue,
    telegram_api_request,
)
from app.services.telegram_security import TelegramSecurityContext, record_telegram_event

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.storage_path / "telegram_config.json"
UPLOAD_DIR = settings.storage_path / "telegram_uploads"

# Compatibility/runtime visibility only. Durable approval rows remain authoritative.
PENDING_ENTRIES: dict[tuple[int, int], dict[str, Any]] = {}
pending_entries_lock = threading.RLock()

bot_thread: Optional[threading.Thread] = None
stop_event = threading.Event()


def _encrypt_token(token: str) -> str:
    return encrypt_value(token)


def _decrypt_token(encrypted_token: str) -> Optional[str]:
    try:
        return decrypt_value(encrypted_token)
    except Exception:
        return None


def get_telegram_token() -> Optional[str]:
    """Read the configured token without exposing it to an API response or log."""

    if not CONFIG_PATH.exists():
        return None
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if config.get("is_active") and config.get("encrypted_token"):
            return _decrypt_token(config["encrypted_token"])
    except Exception:
        logger.info("Telegram configuration access failed")
    return None


def save_telegram_config(token: str, is_active: bool = True) -> bool:
    """Legacy encrypted-file storage retained until the secret-store remediation stage."""

    try:
        encrypted_token = _encrypt_token(token)
        config = {
            "is_active": bool(is_active),
            "encrypted_token": encrypted_token,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_path = CONFIG_PATH.with_name(f".{CONFIG_PATH.name}.{os.getpid()}.tmp")
        temp_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        temp_path.replace(CONFIG_PATH)
        return True
    except Exception:
        logger.exception("Failed to save Telegram configuration")
        return False


def clear_telegram_config() -> bool:
    try:
        CONFIG_PATH.unlink(missing_ok=True)
        return True
    except Exception:
        logger.exception("Failed to clear Telegram configuration")
        return False


def send_telegram_request(token: str, method: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Compatibility wrapper using bounded Bot API responses and strict host checks."""

    try:
        return telegram_api_request(token, method, payload)
    except TelegramIngestionDenied:
        logger.warning("Telegram API request rejected safely: %s", method)
        return None


def download_file(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("Direct Telegram download is disabled; use the bounded ingestion queue")


def process_document(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("Direct Telegram processing is disabled; use the bounded ingestion queue")


def _audit(
    context: TelegramSecurityContext,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    db = SessionLocal()
    try:
        record_telegram_event(db, action, context=context, details=details)
    finally:
        db.close()


def _forget_pending(context: TelegramSecurityContext) -> None:
    with pending_entries_lock:
        PENDING_ENTRIES.pop(context.pending_key, None)


def clear_pending_for_actor(telegram_chat_id: int, telegram_user_id: int) -> int:
    """Revoke durable approvals and remove one actor's compatibility marker."""

    with pending_entries_lock:
        local_removed = 1 if PENDING_ENTRIES.pop((telegram_chat_id, telegram_user_id), None) else 0
    db = SessionLocal()
    try:
        durable_removed = revoke_actor_pending_operations(
            db,
            telegram_chat_id=telegram_chat_id,
            telegram_user_id=telegram_user_id,
            reason="authorization_deactivated",
        )
    finally:
        db.close()
    return max(local_removed, durable_removed)


def _edit_callback_message(
    token: str,
    context: TelegramSecurityContext,
    message_id: int | None,
    text: str,
) -> None:
    if not message_id:
        return
    send_telegram_request(
        token,
        "editMessageText",
        {
            "chat_id": context.telegram_chat_id,
            "message_id": message_id,
            "text": text,
        },
    )


def handle_callback_query(
    token: str,
    query: dict[str, Any],
    context: TelegramSecurityContext,
) -> None:
    """Consume or cancel one durable, actor-bound approval."""

    message = query.get("message") or {}
    message_id = message.get("message_id")
    callback_query_id = query.get("id")
    parsed = parse_callback_data(query.get("data"))

    if callback_query_id:
        send_telegram_request(
            token,
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id},
        )
    if parsed is None:
        _audit(
            context,
            "telegram_unknown_callback_rejected",
            {"callback_data": str(query.get("data"))[:64]},
        )
        return

    action, operation_id, approval_token = parsed
    db = SessionLocal()
    try:
        if action == "cancel":
            cancel_approval(
                db,
                context,
                operation_id=operation_id,
                token=approval_token,
            )
            _forget_pending(context)
            _edit_callback_message(token, context, message_id, "❌ تم إلغاء العملية الآمنة.")
            return

        _edit_callback_message(
            token,
            context,
            message_id,
            "⏳ تم حجز الموافقة، جاري الترحيل إلى Odoo...",
        )
        result = consume_and_post_approval(
            db,
            context,
            operation_id=operation_id,
            token=approval_token,
        )
        _forget_pending(context)
        send_telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": context.telegram_chat_id,
                "text": (
                    "✅ <b>تم ترحيل القيد مرة واحدة بنجاح!</b>\n\n"
                    f"• <b>رقم العملية الآمنة:</b> {result.operation_id}\n"
                    f"• <b>معرّف القيد:</b> {html.escape(str(result.move_id))}\n"
                    f"• <b>اسم القيد:</b> {html.escape(result.move_name)}\n"
                    f"• <b>معرّف المرفق:</b> {html.escape(str(result.attachment_id or '-'))}"
                ),
                "parse_mode": "HTML",
            },
        )
    except TelegramApprovalDenied as denial:
        _audit(
            context,
            "telegram_approval_callback_denied",
            {"operation_id": operation_id, "reason": denial.reason},
        )
        _edit_callback_message(token, context, message_id, f"❌ {denial.public_message}")
    except Exception:
        logger.exception("Telegram approval callback failed")
        _edit_callback_message(token, context, message_id, "❌ تعذر تنفيذ العملية بصورة آمنة.")
    finally:
        db.close()


def bot_polling_loop(token: str) -> None:
    secure_polling_loop(token)


def start_telegram_bot() -> None:
    global bot_thread
    token = get_telegram_token()
    if not token:
        logger.info("No active Telegram bot token configured; bot remains disabled")
        return
    stop_event.clear()
    bot_thread = threading.Thread(
        target=secure_polling_loop,
        args=(token,),
        daemon=True,
        name="telegram-secure-polling",
    )
    bot_thread.start()
    logger.info("Telegram service started with bounded ingestion")


def stop_telegram_bot() -> None:
    global bot_thread
    stop_event.set()
    shutdown_ingestion_queue()
    if bot_thread:
        bot_thread.join(timeout=3)
        bot_thread = None
    logger.info("Telegram service stopped")
