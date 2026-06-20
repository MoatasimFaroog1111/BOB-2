import os
import json
import time
import threading
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.core import ERPConnection
from app.security.encryption import encrypt_value, decrypt_value
from app.api.v1.erp import propose_transaction, ProposeTransactionRequest, register_document, RegisterDocumentRequest, JournalLineRequest
from app.erp.document_ai import GuardianDocumentAI

CONFIG_PATH = settings.storage_path / "telegram_config.json"
UPLOAD_DIR = settings.storage_path / "telegram_uploads"

# Global memory to store pending transactions for approval
# key: chat_id, value: dict containing proposed lines and metadata
PENDING_ENTRIES: Dict[int, Dict[str, Any]] = {}

# Thread management
bot_thread: Optional[threading.Thread] = None
stop_event = threading.Event()


def _encrypt_token(token: str) -> str:
    """Encrypt the Telegram bot token before storage."""
    return encrypt_value(token)


def _decrypt_token(encrypted_token: str) -> Optional[str]:
    """Decrypt the Telegram bot token from storage."""
    try:
        return decrypt_value(encrypted_token)
    except Exception:
        return None


def get_telegram_token() -> Optional[str]:
    """Get the Telegram bot token from secure storage."""
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if config.get("is_active") and config.get("encrypted_token"):
                # Decrypt the token
                decrypted = _decrypt_token(config["encrypted_token"])
                if decrypted:
                    return decrypted
        except Exception as e:
            # Don't log the actual error to avoid leaking sensitive info
            print(f"[Telegram Bot] Error reading config: Configuration access failed")
    return None


def save_telegram_config(token: str, is_active: bool = True) -> bool:
    """Save Telegram bot configuration with encrypted token."""
    try:
        encrypted_token = _encrypt_token(token)
        config = {
            "is_active": is_active,
            "encrypted_token": encrypted_token,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Telegram Bot] Failed to save config: {e}")
        return False


def clear_telegram_config() -> bool:
    """Clear Telegram configuration (for logout/security)."""
    try:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        return True
    except Exception as e:
        print(f"[Telegram Bot] Failed to clear config: {e}")
        return False

def send_telegram_request(token: str, method: str, payload: dict) -> Optional[dict]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"[Telegram Bot] API call {method} failed: {e}")
        return None

def download_file(token: str, file_path: str, dest_path: Path):
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, str(dest_path))
    except Exception as e:
        print(f"[Telegram Bot] Failed to download file: {e}")

def process_document(token: str, chat_id: int, file_id: str, filename: str):
    # 1. Get file path from Telegram
    file_info = send_telegram_request(token, "getFile", {"file_id": file_id})
    if not file_info or not file_info.get("ok"):
        send_telegram_request(token, "sendMessage", {
            "chat_id": chat_id,
            "text": "❌ فشل تحميل معلومات الملف من تليجرام."
        })
        return

    telegram_file_path = file_info["result"]["file_path"]
    suffix = Path(telegram_file_path).suffix or ".pdf"
    local_filename = f"{file_id}{suffix}"
    local_path = UPLOAD_DIR / local_filename
    
    # 2. Download file
    send_telegram_request(token, "sendMessage", {
        "chat_id": chat_id,
        "text": "⏳ جاري تحميل المستند وتحليله محاسبياً..."
    })
    
    download_file(token, telegram_file_path, local_path)
    
    # 3. OCR and Document AI Analysis
    try:
        doc_ai = GuardianDocumentAI()
        analysis = doc_ai.analyze_document(str(local_path))
        fields = analysis.get("fields", {})
        
        amount = fields.get("total_amount") or fields.get("amount") or 0.0
        partner_name = fields.get("supplier_name") or fields.get("partner_name") or ""
        raw_text = analysis.get("raw_text_preview") or ""
        doc_class = analysis.get("document_class") or "general"
        
        # 4. Propose Entries
        db = SessionLocal()
        try:
            payload = ProposeTransactionRequest(
                filename=filename,
                document_class=doc_class,
                amount=amount,
                date=time.strftime("%Y-%m-%d"),
                partner_name=partner_name,
                raw_text=raw_text
            )
            proposal = propose_transaction(payload=payload, db_session=db)
        finally:
            db.close()
            
        if proposal.get("status") != "success" or not proposal.get("lines"):
            send_telegram_request(token, "sendMessage", {
                "chat_id": chat_id,
                "text": "❌ فشل توليد قيد اليومية المقترح للمستند."
            })
            return
            
        # Save to memory for inline approval
        PENDING_ENTRIES[chat_id] = {
            "proposal": proposal,
            "filename": filename,
            "doc_class": doc_class,
            "amount": amount,
            "partner_name": proposal.get("suggested_partner_name") or partner_name,
            "partner_id": proposal.get("suggested_partner_id"),
            "raw_text": raw_text
        }
        
        import html
        # Format response message in Arabic
        lines_text = ""
        for line in proposal["lines"]:
            dr = f"{line['debit']:,} ر.س" if line['debit'] > 0 else "-"
            cr = f"{line['credit']:,} ر.س" if line['credit'] > 0 else "-"
            safe_acc_name = html.escape(str(line['account_name']))
            safe_line_name = html.escape(str(line['name']))
            lines_text += f"▪️ <b>{safe_acc_name}</b>\n   مدين: <code>{dr}</code> | دائن: <code>{cr}</code>\n   البيان: {safe_line_name}\n\n"
            
        safe_filename = html.escape(str(filename))
        safe_partner = html.escape(str(proposal.get('suggested_partner_name') or 'غير محدد'))
        safe_journal = html.escape(str(proposal.get('journal_name') or ''))
        
        msg = (
            "✅ <b>تم تحليل المستند بنجاح!</b>\n\n"
            f"• 📁 <b>الملف:</b> {safe_filename}\n"
            f"• 💰 <b>المبلغ الإجمالي:</b> {amount:,} ر.س\n"
            f"• 🏢 <b>الشريك المقترح:</b> {safe_partner}\n"
            f"• 📑 <b>اليومية المقترحة:</b> {safe_journal}\n\n"
            f"<b>القيود المقترحة (Double-Entry):</b>\n\n{lines_text}"
            "هل تريد ترحيل هذا القيد ومرفقه فورياً إلى Odoo؟"
        )
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "ترحيل القيد ✅", "callback_data": "post_entry"},
                    {"text": "إلغاء ❌", "callback_data": "cancel_entry"}
                ]
            ]
        }
        
        send_telegram_request(token, "sendMessage", {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "reply_markup": keyboard
        })
        
    except Exception as e:
        print(f"[Telegram Bot] Error processing document: {e}")
        send_telegram_request(token, "sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ حدث خطأ أثناء معالجة المستند: {str(e)}"
        })

def handle_callback_query(token: str, query: dict):
    chat_id = query["message"]["chat"]["id"]
    message_id = query["message"]["message_id"]
    data = query.get("data")
    callback_query_id = query["id"]
    
    # Acknowledge callback query
    send_telegram_request(token, "answerCallbackQuery", {"callback_query_id": callback_query_id})
    
    if chat_id not in PENDING_ENTRIES:
        send_telegram_request(token, "editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": "❌ لا يوجد قيد معلق لهذا المستند حالياً."
        })
        return
        
    pending = PENDING_ENTRIES[chat_id]
    
    if data == "cancel_entry":
        del PENDING_ENTRIES[chat_id]
        send_telegram_request(token, "editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": "❌ تم إلغاء ترحيل القيد بنجاح."
        })
        
    elif data == "post_entry":
        proposal = pending["proposal"]
        
        send_telegram_request(token, "editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": "⏳ جاري تسجيل القيد في Odoo..."
        })
        
        db = SessionLocal()
        try:
            # Prepare Lines for registration endpoint schema
            lines_payload = [
                JournalLineRequest(
                    account_id=line["account_id"],
                    account_name=line["account_name"],
                    debit=line["debit"],
                    credit=line["credit"],
                    name=line["name"],
                    partner_id=pending["partner_id"]
                ) for line in proposal["lines"]
            ]
            
            reg_payload = RegisterDocumentRequest(
                filename=pending["filename"],
                document_class=pending["doc_class"],
                amount=pending["amount"],
                date=time.strftime("%Y-%m-%d"),
                partner_name=pending["partner_name"],
                partner_id=pending["partner_id"],
                ref=f"TG Bot: {pending['filename']}",
                raw_text=pending["raw_text"],
                lines=lines_payload
            )
            
            # Post to Odoo
            res = register_document(payload=reg_payload, db_session=db)
            
            del PENDING_ENTRIES[chat_id]
            
            import html
            safe_res_message = html.escape(str(res.get('message') or ''))
            safe_attachment_id = html.escape(str(res.get('attachment_id') or '-'))
            
            msg = (
                "✅ <b>تم ترحيل القيد بنجاح إلى Odoo!</b>\n\n"
                f"• <b>حالة الترحيل:</b> {safe_res_message}\n"
                f"• <b>مُعرّف المرفق:</b> {safe_attachment_id}"
            )
            
            send_telegram_request(token, "sendMessage", {
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "HTML"
            })
            
        except Exception as e:
            print(f"[Telegram Bot] Registration failed: {e}")
            send_telegram_request(token, "sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ فشل ترحيل القيد إلى Odoo: {str(e)}"
            })
        finally:
            db.close()

def bot_polling_loop(token: str):
    print(f"[Telegram Bot] Polling loop started for bot token: {token[:10]}...")
    last_update_id = 0
    
    while not stop_event.is_set():
        updates = send_telegram_request(token, "getUpdates", {
            "offset": last_update_id,
            "timeout": 20
        })
        
        if not updates or not updates.get("ok"):
            # Sleep briefly on error or empty response to prevent CPU spinning
            time.sleep(3)
            continue
            
        for update in updates.get("result", []):
            last_update_id = max(last_update_id, update["update_id"] + 1)
            
            # 1. Handle Callback Queries
            if "callback_query" in update:
                handle_callback_query(token, update["callback_query"])
                continue
                
            # 2. Handle Messages
            if "message" not in update:
                continue
                
            message = update["message"]
            chat_id = message["chat"]["id"]
            
            # Ignore messages that are older than 2 minutes
            msg_date = message.get("date", 0)
            if time.time() - msg_date > 120:
                continue
                
            # Handle text commands
            if "text" in message:
                text = message["text"].strip()
                if text.startswith("/start"):
                    welcome = (
                        "🤖 <b>مرحباً بك في مساعد GuardianAI المحاسبي!</b>\n\n"
                        "أنا هنا لمساعدتك في أتمتة القيود المحاسبية وترحيلها إلى Odoo.\n\n"
                        "💡 <b>كيفية الاستخدام:</b>\n"
                        "1. أرسل لي أي فواتير أو إيصالات (كصورة أو ملف PDF).\n"
                        "2. سأقوم بقراءة البيانات واستخراج المبالغ والشركاء تلقائياً باستخدام محرك الـ OCR.\n"
                        "3. سأقترح عليك قيداً مزدوجاً متوازناً، وبضغطة زر واحدة يمكنك ترحيله إلى Odoo."
                    )
                    send_telegram_request(token, "sendMessage", {
                        "chat_id": chat_id,
                        "text": welcome,
                        "parse_mode": "HTML"
                    })
                else:
                    # Echo or chat reply
                    send_telegram_request(token, "sendMessage", {
                        "chat_id": chat_id,
                        "text": "ℹ️ يرجى إرسال ملف مستند (PDF أو صورة) للبدء بالتحليل التلقائي للقيود."
                    })
                continue
                
            # Handle photo or document uploads
            file_id = None
            filename = "document.pdf"
            
            if "document" in message:
                doc = message["document"]
                file_id = doc["file_id"]
                filename = doc.get("file_name", "document.pdf")
                
            elif "photo" in message:
                # Get largest photo size
                photo = message["photo"][-1]
                file_id = photo["file_id"]
                filename = f"photo_{file_id[:8]}.jpg"
                
            if file_id:
                # Process document in a separate thread to not block polling
                proc_thread = threading.Thread(
                    target=process_document,
                    args=(token, chat_id, file_id, filename)
                )
                proc_thread.start()

def start_telegram_bot():
    global bot_thread, stop_event
    token = get_telegram_token()
    if not token:
        print("[Telegram Bot] No active bot token configured. Bot is disabled.")
        return
        
    stop_event.clear()
    bot_thread = threading.Thread(target=bot_polling_loop, args=(token,), daemon=True)
    bot_thread.start()
    print("[Telegram Bot] Service successfully started in background thread.")

def stop_telegram_bot():
    global bot_thread, stop_event
    stop_event.set()
    if bot_thread:
        bot_thread.join(timeout=3)
        bot_thread = None
        print("[Telegram Bot] Service successfully stopped.")
