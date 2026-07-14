import html
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.db.database import SessionLocal
from app.erp.document_ai import GuardianDocumentAI
from app.security.encryption import decrypt_value, encrypt_value
from app.services.telegram_accounting_service import (
    TelegramApprovalDenied,
    build_callback_data,
    cancel_approval,
    consume_and_post_approval,
    create_document_approval,
    parse_callback_data,
    revoke_actor_pending_operations,
)
from app.services.telegram_security import (
    TelegramAuthorizationDenied,
    TelegramSecurityContext,
    authorize_telegram_actor,
    record_telegram_event,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.storage_path / "telegram_config.json"
UPLOAD_DIR = settings.storage_path / "telegram_uploads"

# Compatibility/runtime visibility only. The database approval row is the source of truth.
# No proposal payload or approval token is kept in this process-local map.
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
    """Get the Telegram bot token without logging or returning it to clients."""
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if config.get("is_active") and config.get("encrypted_token"):
                return _decrypt_token(config["encrypted_token"])
        except Exception:
            logger.info("[Telegram Bot] Configuration access failed")
    return None


def save_telegram_config(token: str, is_active: bool = True) -> bool:
    try:
        encrypted_token = _encrypt_token(token)
        config = {
            "is_active": is_active,
            "encrypted_token": encrypted_token,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return True
    except Exception:
        logger.exception("[Telegram Bot] Failed to save configuration")
        return False


def clear_telegram_config() -> bool:
    try:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        return True
    except Exception:
        logger.exception("[Telegram Bot] Failed to clear configuration")
        return False


def send_telegram_request(token: str, method: str, payload: dict) -> Optional[dict]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        logger.warning("[Telegram Bot] API call failed: %s", method)
        return None


def download_file(token: str, file_path: str, destination: Path) -> None:
    """Legacy downloader retained until the bounded-streaming remediation stage."""
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(destination))


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


def _remember_pending(context: TelegramSecurityContext, operation_id: int) -> None:
    with pending_entries_lock:
        PENDING_ENTRIES[context.pending_key] = {"operation_id": operation_id}


def _forget_pending(context: TelegramSecurityContext) -> None:
    with pending_entries_lock:
        PENDING_ENTRIES.pop(context.pending_key, None)


def clear_pending_for_actor(telegram_chat_id: int, telegram_user_id: int) -> int:
    """Revoke durable approvals and clear only one actor's local runtime marker."""
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


def _format_proposal_message(proposal: dict[str, Any], expires_at: str) -> str:
    lines_text = ""
    for line in proposal.get("lines") or []:
        debit = float(line.get("debit") or 0.0)
        credit = float(line.get("credit") or 0.0)
        debit_text = f"{debit:,.2f} ر.س" if debit > 0 else "-"
        credit_text = f"{credit:,.2f} ر.س" if credit > 0 else "-"
        lines_text += (
            f"▪️ <b>{html.escape(str(line.get('account_name') or ''))}</b>\n"
            f"   مدين: <code>{debit_text}</code> | دائن: <code>{credit_text}</code>\n"
            f"   البيان: {html.escape(str(line.get('name') or ''))}\n\n"
        )
    return (
        "✅ <b>تم تحليل المستند وإنشاء موافقة آمنة!</b>\n\n"
        f"• 📁 <b>الملف:</b> {html.escape(str(proposal.get('filename') or ''))}\n"
        f"• 💰 <b>المبلغ:</b> {float(proposal.get('amount') or 0):,.2f} ر.س\n"
        f"• 🏢 <b>الشريك:</b> {html.escape(str(proposal.get('partner_name') or 'غير محدد'))}\n"
        f"• 📑 <b>اليومية:</b> {html.escape(str(proposal.get('journal_name') or ''))}\n"
        f"• ⏱️ <b>تنتهي الموافقة:</b> {html.escape(expires_at)} UTC\n\n"
        f"<b>القيود المقترحة:</b>\n\n{lines_text}"
        "زر الاعتماد صالح لمرة واحدة فقط، ومربوط بهويتك وبالمحادثة وبصمة المحتوى."
    )


def process_document(
    token: str,
    context: TelegramSecurityContext,
    file_id: str,
    filename: str,
) -> None:
    chat_id = context.telegram_chat_id
    local_path: Path | None = None
    try:
        _audit(
            context,
            "telegram_document_processing_started",
            {"filename": Path(filename).name, "file_id": file_id},
        )
        file_info = send_telegram_request(token, "getFile", {"file_id": file_id})
        if not file_info or not file_info.get("ok"):
            raise RuntimeError("telegram_file_metadata_unavailable")

        telegram_file_path = file_info["result"]["file_path"]
        suffix = Path(telegram_file_path).suffix or ".pdf"
        local_path = UPLOAD_DIR / f"{file_id}{suffix}"
        send_telegram_request(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": "⏳ جاري تحميل المستند وتحليله محاسبياً..."},
        )
        download_file(token, telegram_file_path, local_path)

        analysis = GuardianDocumentAI().analyze_document(str(local_path))
        fields = analysis.get("fields", {})
        amount = fields.get("total_amount") or fields.get("amount") or 0
        partner_name = fields.get("supplier_name") or fields.get("partner_name") or ""
        raw_text = analysis.get("raw_text_preview") or ""
        document_class = analysis.get("document_class") or "general"

        db = SessionLocal()
        try:
            approval = create_document_approval(
                db,
                context,
                filename=filename,
                document_class=document_class,
                amount=amount,
                transaction_date=time.strftime("%Y-%m-%d"),
                partner_name=partner_name,
                raw_text=raw_text,
                file_path=str(local_path),
                source="telegram",
            )
        finally:
            db.close()

        approve_callback = build_callback_data(
            "approve", approval.operation_id, approval.approval_token
        )
        cancel_callback = build_callback_data(
            "cancel", approval.operation_id, approval.approval_token
        )
        _remember_pending(context, approval.operation_id)
        send_telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": _format_proposal_message(
                    approval.proposal,
                    approval.expires_at.replace(microsecond=0).isoformat(),
                ),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "ترحيل القيد ✅", "callback_data": approve_callback},
                        {"text": "إلغاء ❌", "callback_data": cancel_callback},
                    ]]
                },
            },
        )
        _audit(
            context,
            "telegram_document_pending_approval",
            {
                "operation_id": approval.operation_id,
                "filename": Path(filename).name,
                "expires_at": approval.expires_at.isoformat(),
            },
        )
    except TelegramApprovalDenied as denial:
        logger.warning("[Telegram Bot] Approval creation denied: %s", denial.reason)
        if local_path:
            local_path.unlink(missing_ok=True)
        _audit(context, "telegram_document_approval_denied", {"reason": denial.reason})
        send_telegram_request(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": f"❌ {denial.public_message}"},
        )
    except Exception:
        logger.exception("[Telegram Bot] Document processing failed")
        if local_path:
            local_path.unlink(missing_ok=True)
        try:
            _audit(
                context,
                "telegram_document_processing_failed",
                {"filename": Path(filename).name},
            )
        except Exception:
            logger.exception("[Telegram Bot] Failed to audit document processing failure")
        send_telegram_request(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": "❌ تعذر معالجة المستند بصورة آمنة."},
        )


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
        {"chat_id": context.telegram_chat_id, "message_id": message_id, "text": text},
    )


def handle_callback_query(
    token: str,
    query: dict,
    context: TelegramSecurityContext,
) -> None:
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

        _edit_callback_message(token, context, message_id, "⏳ تم حجز الموافقة، جاري الترحيل إلى Odoo...")
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
        logger.exception("[Telegram Bot] Approval callback failed")
        _edit_callback_message(token, context, message_id, "❌ تعذر تنفيذ العملية بصورة آمنة.")
    finally:
        db.close()


def _authorize_update(
    *,
    telegram_user_id: int | None,
    telegram_chat_id: int | None,
    chat_type: str | None,
    required_permissions: tuple[str, ...],
    event_type: str,
    update_id: int | None,
) -> TelegramSecurityContext:
    db = SessionLocal()
    try:
        return authorize_telegram_actor(
            db,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            chat_type=chat_type,
            required_permissions=required_permissions,
            event_type=event_type,
            update_id=update_id,
        )
    finally:
        db.close()


def _deny_callback(token: str, query: dict, denial: TelegramAuthorizationDenied) -> None:
    callback_query_id = query.get("id")
    if callback_query_id:
        send_telegram_request(
            token,
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
                "text": denial.public_message,
                "show_alert": True,
            },
        )


def bot_polling_loop(token: str) -> None:
    logger.info("[Telegram Bot] Secure polling loop started")
    last_update_id = 0

    while not stop_event.is_set():
        updates = send_telegram_request(
            token,
            "getUpdates",
            {"offset": last_update_id, "timeout": 20},
        )
        if not updates or not updates.get("ok"):
            time.sleep(3)
            continue

        for update in updates.get("result", []):
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                last_update_id = max(last_update_id, update_id + 1)

            query = update.get("callback_query")
            if isinstance(query, dict):
                actor = query.get("from") or {}
                message = query.get("message") or {}
                chat = message.get("chat") or {}
                parsed = parse_callback_data(query.get("data"))
                permissions = (
                    ("post_odoo_entries",)
                    if parsed is not None and parsed[0] == "approve"
                    else ("view_financials",)
                )
                try:
                    context = _authorize_update(
                        telegram_user_id=actor.get("id"),
                        telegram_chat_id=chat.get("id"),
                        chat_type=chat.get("type"),
                        required_permissions=permissions,
                        event_type="callback_query",
                        update_id=update_id,
                    )
                except TelegramAuthorizationDenied as denial:
                    _deny_callback(token, query, denial)
                    continue
                handle_callback_query(token, query, context)
                continue

            message = update.get("message")
            if not isinstance(message, dict):
                continue
            actor = message.get("from") or {}
            chat = message.get("chat") or {}
            document = message.get("document")
            photos = message.get("photo")
            is_upload = isinstance(document, dict) or (isinstance(photos, list) and bool(photos))
            permissions = (
                ("upload_documents", "create_entries")
                if is_upload
                else ("view_financials",)
            )
            try:
                context = _authorize_update(
                    telegram_user_id=actor.get("id"),
                    telegram_chat_id=chat.get("id"),
                    chat_type=chat.get("type"),
                    required_permissions=permissions,
                    event_type="message_upload" if is_upload else "message",
                    update_id=update_id,
                )
            except TelegramAuthorizationDenied as denial:
                chat_id = chat.get("id")
                if isinstance(chat_id, int):
                    send_telegram_request(
                        token,
                        "sendMessage",
                        {"chat_id": chat_id, "text": f"❌ {denial.public_message}"},
                    )
                continue

            message_date = message.get("date", 0)
            if isinstance(message_date, (int, float)) and time.time() - message_date > 120:
                _audit(context, "telegram_stale_message_ignored", {"update_id": update_id})
                continue

            text = message.get("text")
            if isinstance(text, str):
                if text.strip().startswith("/start"):
                    response_text = (
                        "🤖 <b>مرحباً بك في مساعد GuardianAI المحاسبي الآمن!</b>\n\n"
                        "تم التحقق من هويتك وربطك بمستخدم النظام والمؤسسة.\n"
                        "كل موافقة محاسبية تصدر بتوكن مشفر أحادي الاستخدام ومحدد المدة."
                    )
                    parse_mode = "HTML"
                else:
                    response_text = "ℹ️ يرجى إرسال مستند PDF أو صورة للبدء بالتحليل."
                    parse_mode = None
                payload: dict[str, Any] = {
                    "chat_id": context.telegram_chat_id,
                    "text": response_text,
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                send_telegram_request(token, "sendMessage", payload)
                _audit(context, "telegram_text_message_handled", {"command": text[:32]})
                continue

            file_id: str | None = None
            filename = "document.pdf"
            if isinstance(document, dict):
                file_id = document.get("file_id")
                filename = document.get("file_name") or "document.pdf"
            elif isinstance(photos, list) and photos:
                photo = photos[-1]
                if isinstance(photo, dict):
                    file_id = photo.get("file_id")
                    if file_id:
                        filename = f"photo_{file_id[:8]}.jpg"

            if file_id:
                threading.Thread(
                    target=process_document,
                    args=(token, context, file_id, filename),
                    daemon=True,
                    name=f"telegram-document-{context.telegram_user_id}",
                ).start()
            else:
                _audit(context, "telegram_unsupported_message_ignored", {"update_id": update_id})


def start_telegram_bot() -> None:
    global bot_thread, stop_event
    token = get_telegram_token()
    if not token:
        logger.info("[Telegram Bot] No active bot token configured. Bot is disabled.")
        return
    stop_event.clear()
    bot_thread = threading.Thread(
        target=bot_polling_loop,
        args=(token,),
        daemon=True,
        name="telegram-secure-polling",
    )
    bot_thread.start()
    logger.info("[Telegram Bot] Service started through secure polling")


def stop_telegram_bot() -> None:
    global bot_thread, stop_event
    stop_event.set()
    if bot_thread:
        bot_thread.join(timeout=3)
        bot_thread = None
        logger.info("[Telegram Bot] Service stopped")
