import html
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from app.api.v1.erp import (
    JournalLineRequest,
    ProposeTransactionRequest,
    RegisterDocumentRequest,
    propose_transaction,
    register_document,
)
from app.core.config import settings
from app.db.database import SessionLocal
from app.erp.document_ai import GuardianDocumentAI
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value, encrypt_value
from app.services.telegram_security import (
    TelegramAuthorizationDenied,
    TelegramSecurityContext,
    authorize_telegram_actor,
    record_telegram_event,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.storage_path / "telegram_config.json"
UPLOAD_DIR = settings.storage_path / "telegram_uploads"

# Pending work is bound to (chat_id, Telegram user_id), never to chat_id alone.
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
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
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


def clear_pending_for_actor(telegram_chat_id: int, telegram_user_id: int) -> int:
    """Clear only one actor's pending operation and return the number removed."""
    key = (telegram_chat_id, telegram_user_id)
    with pending_entries_lock:
        pending = PENDING_ENTRIES.pop(key, None)
    if not pending:
        return 0
    local_path = pending.get("local_path")
    if local_path:
        try:
            Path(local_path).unlink(missing_ok=True)
        except Exception:
            logger.warning("[Telegram Bot] Could not remove deactivated actor's pending file")
    return 1


def _pending_for_context(context: TelegramSecurityContext) -> dict[str, Any] | None:
    with pending_entries_lock:
        pending = PENDING_ENTRIES.get(context.pending_key)
    if pending is None:
        return None
    if (
        pending.get("telegram_user_id") != context.telegram_user_id
        or pending.get("telegram_chat_id") != context.telegram_chat_id
        or pending.get("organization_id") != context.organization_id
        or pending.get("system_user_id") != context.system_user_id
    ):
        _audit(
            context,
            "telegram_pending_identity_mismatch",
            {"pending_authorization_id": pending.get("authorization_id")},
        )
        return None
    return pending


def process_document(
    token: str,
    context: TelegramSecurityContext,
    file_id: str,
    filename: str,
) -> None:
    chat_id = context.telegram_chat_id
    # The current legacy ERP route still targets organization 1. Fail closed for every
    # other tenant until the independent posting service is completed in the next stage.
    if context.organization_id != 1:
        _audit(
            context,
            "telegram_document_blocked_legacy_tenant",
            {"filename": Path(filename).name},
        )
        send_telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": "❌ الترحيل عبر Telegram غير متاح لهذه المؤسسة حتى اكتمال خدمة الترحيل المعزولة.",
            },
        )
        return

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
        amount = fields.get("total_amount") or fields.get("amount") or 0.0
        partner_name = fields.get("supplier_name") or fields.get("partner_name") or ""
        raw_text = analysis.get("raw_text_preview") or ""
        document_class = analysis.get("document_class") or "general"

        db = SessionLocal()
        try:
            proposal = propose_transaction(
                payload=ProposeTransactionRequest(
                    filename=filename,
                    document_class=document_class,
                    amount=amount,
                    date=time.strftime("%Y-%m-%d"),
                    partner_name=partner_name,
                    raw_text=raw_text,
                ),
                db_session=db,
            )
        finally:
            db.close()

        if proposal.get("status") != "success" or not proposal.get("lines"):
            raise RuntimeError("journal_proposal_failed")

        pending = {
            "proposal": proposal,
            "filename": filename,
            "doc_class": document_class,
            "amount": amount,
            "partner_name": proposal.get("suggested_partner_name") or partner_name,
            "partner_id": proposal.get("suggested_partner_id"),
            "raw_text": raw_text,
            "local_path": str(local_path),
            "authorization_id": context.authorization_id,
            "telegram_user_id": context.telegram_user_id,
            "telegram_chat_id": context.telegram_chat_id,
            "organization_id": context.organization_id,
            "system_user_id": context.system_user_id,
        }
        with pending_entries_lock:
            previous = PENDING_ENTRIES.pop(context.pending_key, None)
            PENDING_ENTRIES[context.pending_key] = pending
        if previous and previous.get("local_path") != str(local_path):
            try:
                Path(previous["local_path"]).unlink(missing_ok=True)
            except Exception:
                logger.warning("[Telegram Bot] Failed to remove replaced pending file")

        lines_text = ""
        for line in proposal["lines"]:
            debit = f"{line['debit']:,} ر.س" if line["debit"] > 0 else "-"
            credit = f"{line['credit']:,} ر.س" if line["credit"] > 0 else "-"
            lines_text += (
                f"▪️ <b>{html.escape(str(line['account_name']))}</b>\n"
                f"   مدين: <code>{debit}</code> | دائن: <code>{credit}</code>\n"
                f"   البيان: {html.escape(str(line['name']))}\n\n"
            )

        message = (
            "✅ <b>تم تحليل المستند بنجاح!</b>\n\n"
            f"• 📁 <b>الملف:</b> {html.escape(str(filename))}\n"
            f"• 💰 <b>المبلغ الإجمالي:</b> {amount:,} ر.س\n"
            f"• 🏢 <b>الشريك المقترح:</b> {html.escape(str(proposal.get('suggested_partner_name') or 'غير محدد'))}\n"
            f"• 📑 <b>اليومية المقترحة:</b> {html.escape(str(proposal.get('journal_name') or ''))}\n\n"
            f"<b>القيود المقترحة:</b>\n\n{lines_text}"
            "هل تريد ترحيل هذا القيد ومرفقه إلى Odoo؟"
        )
        send_telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "ترحيل القيد ✅", "callback_data": "post_entry"},
                        {"text": "إلغاء ❌", "callback_data": "cancel_entry"},
                    ]]
                },
            },
        )
        _audit(
            context,
            "telegram_document_pending_approval",
            {"filename": Path(filename).name, "document_class": document_class},
        )
    except Exception:
        logger.exception("[Telegram Bot] Document processing failed")
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


def _upload_attachment_to_odoo(
    move_id: int,
    filename: str,
    file_path: str,
    db_session,
    organization_id: int,
) -> int:
    import base64

    from app.erp.factory import get_erp_provider

    connection = (
        db_session.query(ERPConnection)
        .filter(
            ERPConnection.organization_id == organization_id,
            ERPConnection.is_active.is_(True),
        )
        .first()
    )
    if not connection:
        raise RuntimeError("No active ERP connection")

    secret_data = json.loads(decrypt_value(connection.encrypted_secret_ref))
    erp = get_erp_provider(
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=secret_data["username"],
        password=secret_data["password"],
    )
    with open(file_path, "rb") as source:
        file_data = base64.b64encode(source.read()).decode("utf-8")
    return erp.execute_kw(
        "ir.attachment",
        "create",
        [{
            "name": filename,
            "type": "binary",
            "datas": file_data,
            "res_model": "account.move",
            "res_id": move_id,
        }],
    )


def handle_callback_query(
    token: str,
    query: dict,
    context: TelegramSecurityContext,
) -> None:
    message = query.get("message") or {}
    message_id = message.get("message_id")
    chat_id = context.telegram_chat_id
    callback_query_id = query.get("id")
    data = query.get("data")

    if callback_query_id:
        send_telegram_request(
            token,
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id},
        )

    pending = _pending_for_context(context)
    if pending is None:
        if message_id:
            send_telegram_request(
                token,
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "❌ لا توجد عملية معلقة تخص هذا المستخدم.",
                },
            )
        return

    if data == "cancel_entry":
        clear_pending_for_actor(chat_id, context.telegram_user_id)
        _audit(context, "telegram_pending_entry_cancelled")
        if message_id:
            send_telegram_request(
                token,
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "❌ تم إلغاء ترحيل القيد.",
                },
            )
        return

    if data != "post_entry":
        _audit(context, "telegram_unknown_callback_rejected", {"callback_data": str(data)[:64]})
        return

    if not context.has_permission("post_odoo_entries"):
        _audit(context, "telegram_post_permission_denied")
        send_telegram_request(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": "❌ لا تملك صلاحية ترحيل القيود إلى Odoo."},
        )
        return

    if message_id:
        send_telegram_request(
            token,
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "⏳ جاري تسجيل القيد في Odoo...",
            },
        )

    db = SessionLocal()
    try:
        proposal = pending["proposal"]
        lines = [
            JournalLineRequest(
                account_id=line["account_id"],
                account_name=line["account_name"],
                debit=line["debit"],
                credit=line["credit"],
                name=line["name"],
                partner_id=pending["partner_id"],
            )
            for line in proposal["lines"]
        ]
        response = register_document(
            payload=RegisterDocumentRequest(
                filename=pending["filename"],
                document_class=pending["doc_class"],
                amount=pending["amount"],
                date=time.strftime("%Y-%m-%d"),
                partner_name=pending["partner_name"],
                partner_id=pending["partner_id"],
                ref=f"TG Bot: {pending['filename']}",
                raw_text=pending["raw_text"],
                lines=lines,
                file_path=pending.get("local_path"),
            ),
            db_session=db,
        )
        attachment_id = response.get("attachment_id")
        move_id = response.get("move_id")
        local_file = pending.get("local_path")
        if not attachment_id and move_id and local_file and Path(local_file).exists():
            attachment_id = _upload_attachment_to_odoo(
                move_id,
                pending["filename"],
                local_file,
                db,
                context.organization_id,
            )
        clear_pending_for_actor(chat_id, context.telegram_user_id)
        _audit(
            context,
            "telegram_entry_posted_to_odoo",
            {"move_id": move_id, "attachment_id": attachment_id},
        )
        send_telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": (
                    "✅ <b>تم ترحيل القيد بنجاح إلى Odoo!</b>\n\n"
                    f"• <b>مُعرّف القيد:</b> {html.escape(str(move_id or '-'))}\n"
                    f"• <b>مُعرّف المرفق:</b> {html.escape(str(attachment_id or '-'))}"
                ),
                "parse_mode": "HTML",
            },
        )
    except Exception:
        logger.exception("[Telegram Bot] Odoo registration failed")
        try:
            _audit(context, "telegram_entry_post_failed")
        except Exception:
            logger.exception("[Telegram Bot] Failed to audit posting failure")
        send_telegram_request(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": "❌ تعذر ترحيل القيد بصورة آمنة."},
        )
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
                callback_data = query.get("data")
                permissions = (
                    ("post_odoo_entries",)
                    if callback_data == "post_entry"
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
                        "يمكنك إرسال فاتورة أو إيصال بعد التأكد من امتلاك صلاحيات الرفع وإنشاء القيود."
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
