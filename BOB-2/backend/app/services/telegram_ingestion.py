"""Bounded, fail-closed Telegram document ingestion.

The polling thread never downloads or parses a document directly. Valid uploads enter a
bounded queue served by a fixed number of daemon workers. Every byte is downloaded from
a validated Telegram URL into an atomically renamed file under the dedicated upload
folder, with declared-size, response-size, streaming-size, malware, and content checks
before OCR or accounting logic runs.
"""

from __future__ import annotations

import collections
import html
import json
import logging
import os
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from app.core.config import settings
from app.db.database import SessionLocal
from app.erp.document_ai import GuardianDocumentAI
from app.security.file_validation import (
    FileValidationError,
    sanitize_filename,
    scan_for_malware,
    validate_file_content,
    validate_file_extension,
    validate_file_path,
    validate_file_size,
)
from app.services.telegram_accounting_service import (
    TelegramApprovalDenied,
    build_callback_data,
    cancel_approval,
    create_document_approval,
    parse_callback_data,
)
from app.services.telegram_approval_cleanup import expire_pending_approvals
from app.services.telegram_security import (
    TelegramAuthorizationDenied,
    TelegramSecurityContext,
    authorize_telegram_actor,
    record_telegram_event,
)

logger = logging.getLogger(__name__)

TELEGRAM_API_HOST = "api.telegram.org"
TELEGRAM_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
_FILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,512}$")
_METHOD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_TOKEN_PATTERN = re.compile(r"^[0-9]{5,20}:[A-Za-z0-9_-]{20,100}$")
_REMOTE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,512}$")

UPLOAD_DIR = settings.storage_path / "telegram_uploads"


class TelegramIngestionDenied(Exception):
    """Safe rejection before or during bounded Telegram ingestion."""

    def __init__(self, reason: str, public_message: str = "تعذر معالجة الملف بصورة آمنة."):
        super().__init__(reason)
        self.reason = reason
        self.public_message = public_message


@dataclass(frozen=True, slots=True)
class TelegramIngestionJob:
    job_id: str
    token: str
    context: TelegramSecurityContext
    file_id: str
    filename: str
    declared_size: int
    update_id: int | None
    submitted_monotonic: float

    @property
    def actor_key(self) -> tuple[int, int]:
        return (self.context.telegram_chat_id, self.context.telegram_user_id)

    @property
    def organization_id(self) -> int:
        return self.context.organization_id


Processor = Callable[[TelegramIngestionJob], None]
Notifier = Callable[[TelegramIngestionJob, str], None]
Auditor = Callable[[TelegramIngestionJob, str, dict[str, Any]], None]


def _max_upload_bytes() -> int:
    return settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _validate_bot_token(token: str) -> None:
    if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
        raise TelegramIngestionDenied("invalid_bot_token", "إعداد Telegram Bot غير صالح.")


def _validate_api_method(method: str) -> None:
    if not isinstance(method, str) or not _METHOD_PATTERN.fullmatch(method):
        raise TelegramIngestionDenied("invalid_telegram_method")


def _validate_telegram_url(url: str, *, expected_path_prefix: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != TELEGRAM_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith(expected_path_prefix)
    ):
        raise TelegramIngestionDenied(
            "telegram_redirect_host_rejected",
            "رفض النظام وجهة تنزيل غير موثوقة.",
        )


def telegram_api_request(
    token: str,
    method: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any] | None:
    """Call a Bot API method with a bounded response and strict final-host check."""

    try:
        _validate_bot_token(token)
        _validate_api_method(method)
        url = f"https://{TELEGRAM_API_HOST}/bot{token}/{method}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "GuardianAI-Telegram/1.0",
            },
            method="POST",
        )
        timeout = timeout_seconds or settings.TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS
        with opener(request, timeout=timeout) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else url
            _validate_telegram_url(final_url, expected_path_prefix="/bot")
            content_length = response.headers.get("Content-Length") if response.headers else None
            if content_length:
                try:
                    if int(content_length) > settings.TELEGRAM_API_RESPONSE_MAX_BYTES:
                        raise TelegramIngestionDenied("telegram_api_response_too_large")
                except ValueError as exc:
                    raise TelegramIngestionDenied("telegram_api_invalid_content_length") from exc
            body = response.read(settings.TELEGRAM_API_RESPONSE_MAX_BYTES + 1)
            if len(body) > settings.TELEGRAM_API_RESPONSE_MAX_BYTES:
                raise TelegramIngestionDenied("telegram_api_response_too_large")
            decoded = json.loads(body.decode("utf-8"))
            return decoded if isinstance(decoded, dict) else None
    except TelegramIngestionDenied:
        raise
    except Exception:
        logger.warning("Telegram API call failed safely: %s", method)
        return None


def validate_telegram_remote_path(file_path: Any) -> str:
    """Accept only a relative Telegram-owned POSIX path, never a URL or host."""

    if not isinstance(file_path, str) or not _REMOTE_PATH_PATTERN.fullmatch(file_path):
        raise TelegramIngestionDenied("telegram_file_path_invalid")
    if "\\" in file_path or "//" in file_path or "%" in file_path:
        raise TelegramIngestionDenied("telegram_file_path_invalid")
    path = PurePosixPath(file_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise TelegramIngestionDenied("telegram_file_path_invalid")
    return file_path


def _telegram_file_url(token: str, file_path: str) -> str:
    _validate_bot_token(token)
    validated = validate_telegram_remote_path(file_path)
    encoded_path = "/".join(urllib.parse.quote(part, safe="._-") for part in PurePosixPath(validated).parts)
    url = f"https://{TELEGRAM_API_HOST}/file/bot{token}/{encoded_path}"
    _validate_telegram_url(url, expected_path_prefix="/file/bot")
    return url


def validate_declared_file_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TelegramIngestionDenied(
            "telegram_file_size_missing",
            "لا يمكن التحقق من حجم الملف قبل التنزيل.",
        )
    if value > _max_upload_bytes():
        raise TelegramIngestionDenied(
            "telegram_file_too_large",
            f"حجم الملف يتجاوز الحد المسموح وهو {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )
    return value


def validate_telegram_filename(filename: Any) -> str:
    if not isinstance(filename, str):
        raise TelegramIngestionDenied("telegram_filename_missing")
    safe_name = sanitize_filename(filename.strip())
    if not safe_name or safe_name in {".", "..", "unnamed_file"}:
        raise TelegramIngestionDenied("telegram_filename_invalid")
    try:
        validate_file_extension(safe_name)
    except FileValidationError as exc:
        raise TelegramIngestionDenied("telegram_extension_rejected", str(exc.detail)) from exc
    extension = Path(safe_name).suffix.lower()
    if extension not in TELEGRAM_DOCUMENT_EXTENSIONS:
        raise TelegramIngestionDenied(
            "telegram_extension_rejected",
            "يسمح Telegram حاليًا بملفات PDF والصور الآمنة فقط.",
        )
    return safe_name


def validate_telegram_file_id(file_id: Any) -> str:
    if not isinstance(file_id, str) or not _FILE_ID_PATTERN.fullmatch(file_id):
        raise TelegramIngestionDenied("telegram_file_id_invalid")
    return file_id


def bounded_download_telegram_file(
    token: str,
    remote_file_path: str,
    destination: Path,
    *,
    expected_size: int,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> int:
    """Stream a Telegram file with an enforced byte ceiling and atomic rename."""

    expected_size = validate_declared_file_size(expected_size)
    remote_file_path = validate_telegram_remote_path(remote_file_path)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(UPLOAD_DIR, 0o700)
    except OSError:
        pass

    destination = destination.resolve()
    validate_file_path(str(destination), str(UPLOAD_DIR.resolve()))
    if destination.exists():
        raise TelegramIngestionDenied("telegram_destination_exists")

    part_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    validate_file_path(str(part_path.resolve()), str(UPLOAD_DIR.resolve()))
    url = _telegram_file_url(token, remote_file_path)
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "GuardianAI-Telegram/1.0",
        },
        method="GET",
    )
    total = 0
    try:
        with opener(request, timeout=settings.TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else url
            _validate_telegram_url(final_url, expected_path_prefix="/file/bot")
            content_length = response.headers.get("Content-Length") if response.headers else None
            if content_length:
                try:
                    response_size = int(content_length)
                except ValueError as exc:
                    raise TelegramIngestionDenied("telegram_download_invalid_content_length") from exc
                if response_size <= 0 or response_size > _max_upload_bytes():
                    raise TelegramIngestionDenied("telegram_download_size_rejected")
                if response_size != expected_size:
                    raise TelegramIngestionDenied("telegram_file_size_changed")

            with part_path.open("xb") as target:
                while True:
                    chunk = response.read(settings.TELEGRAM_DOWNLOAD_CHUNK_SIZE_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _max_upload_bytes() or total > expected_size:
                        raise TelegramIngestionDenied("telegram_download_stream_limit_exceeded")
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

        if total != expected_size:
            raise TelegramIngestionDenied("telegram_download_size_mismatch")
        part_path.replace(destination)
        try:
            os.chmod(destination, 0o600)
        except OSError:
            pass
        return total
    except Exception:
        part_path.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def _read_and_validate_download(path: Path, filename: str) -> bytes:
    max_bytes = _max_upload_bytes()
    with path.open("rb") as source:
        content = source.read(max_bytes + 1)
    try:
        validate_file_size(content)
        extension = Path(filename).suffix.lower()
        scan_for_malware(content)
        validate_file_content(content, extension)
    except FileValidationError as exc:
        raise TelegramIngestionDenied("telegram_file_validation_failed", str(exc.detail)) from exc
    return content


def _audit_context(
    context: TelegramSecurityContext,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    db = SessionLocal()
    try:
        record_telegram_event(db, action, context=context, details=details)
    finally:
        db.close()


def _notify_context(token: str, context: TelegramSecurityContext, text: str) -> None:
    try:
        telegram_api_request(
            token,
            "sendMessage",
            {"chat_id": context.telegram_chat_id, "text": text},
        )
    except Exception:
        logger.warning("Unable to deliver Telegram ingestion notification")


def _format_proposal_message(proposal: dict[str, Any], expires_at: str) -> str:
    line_parts: list[str] = []
    for line in proposal.get("lines") or []:
        debit = float(line.get("debit") or 0.0)
        credit = float(line.get("credit") or 0.0)
        line_parts.append(
            "\n".join(
                [
                    f"▪️ <b>{html.escape(str(line.get('account_name') or ''))}</b>",
                    f"   مدين: <code>{debit:,.2f}</code> | دائن: <code>{credit:,.2f}</code>",
                    f"   البيان: {html.escape(str(line.get('name') or ''))}",
                ]
            )
        )
    lines_text = "\n\n".join(line_parts)
    return (
        "✅ <b>تم تحليل المستند وإنشاء موافقة آمنة!</b>\n\n"
        f"• 📁 <b>الملف:</b> {html.escape(str(proposal.get('filename') or ''))}\n"
        f"• 💰 <b>المبلغ:</b> {float(proposal.get('amount') or 0):,.2f} ر.س\n"
        f"• 🏢 <b>الشريك:</b> {html.escape(str(proposal.get('partner_name') or 'غير محدد'))}\n"
        f"• 📑 <b>اليومية:</b> {html.escape(str(proposal.get('journal_name') or ''))}\n"
        f"• ⏱️ <b>تنتهي الموافقة:</b> {html.escape(expires_at)} UTC\n\n"
        f"<b>القيود المقترحة:</b>\n\n{lines_text}\n\n"
        "زر الاعتماد صالح لمرة واحدة فقط ومربوط بهويتك والمحادثة وبصمة الملف."
    )


def process_ingestion_job(job: TelegramIngestionJob) -> None:
    """Download, validate, scan, OCR, and propose one queued document."""

    local_path: Path | None = None
    retain_for_approval = False
    approval = None
    try:
        _audit_context(
            job.context,
            "telegram_ingestion_started",
            {
                "job_id": job.job_id,
                "filename": job.filename,
                "declared_size": job.declared_size,
                "update_id": job.update_id,
            },
        )
        file_info = telegram_api_request(job.token, "getFile", {"file_id": job.file_id})
        if not file_info or not file_info.get("ok") or not isinstance(file_info.get("result"), dict):
            raise TelegramIngestionDenied("telegram_file_metadata_unavailable")
        result = file_info["result"]
        remote_size = validate_declared_file_size(result.get("file_size"))
        if remote_size != job.declared_size:
            raise TelegramIngestionDenied(
                "telegram_file_size_changed",
                "تغير حجم الملف بين الرسالة والتنزيل، لذلك تم رفضه.",
            )
        remote_path = validate_telegram_remote_path(result.get("file_path"))
        extension = Path(job.filename).suffix.lower()
        local_path = (UPLOAD_DIR / f"{uuid.uuid4().hex}{extension}").resolve()
        validate_file_path(str(local_path), str(UPLOAD_DIR.resolve()))

        _notify_context(job.token, job.context, "⏳ تم حجز الملف في طابور آمن وبدأ تنزيله وفحصه...")
        downloaded_size = bounded_download_telegram_file(
            job.token,
            remote_path,
            local_path,
            expected_size=remote_size,
        )
        _read_and_validate_download(local_path, job.filename)

        analysis = GuardianDocumentAI().analyze_document(str(local_path))
        if isinstance(analysis, dict):
            fields = analysis.get("fields", {})
            raw_text = analysis.get("raw_text_preview") or ""
            document_class = analysis.get("document_class") or "general"
        else:
            fields = {}
            raw_text = ""
            document_class = "general"
        amount = fields.get("total_amount") or fields.get("amount") or 0
        partner_name = fields.get("supplier_name") or fields.get("partner_name") or ""

        db = SessionLocal()
        try:
            approval = create_document_approval(
                db,
                job.context,
                filename=job.filename,
                document_class=document_class,
                amount=amount,
                transaction_date=time.strftime("%Y-%m-%d"),
                partner_name=partner_name,
                raw_text=raw_text,
                file_path=str(local_path),
                source="telegram",
            )
            approve_callback = build_callback_data(
                "approve", approval.operation_id, approval.approval_token
            )
            cancel_callback = build_callback_data(
                "cancel", approval.operation_id, approval.approval_token
            )
            delivery = telegram_api_request(
                job.token,
                "sendMessage",
                {
                    "chat_id": job.context.telegram_chat_id,
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
            if not delivery or not delivery.get("ok"):
                cancel_approval(
                    db,
                    job.context,
                    operation_id=approval.operation_id,
                    token=approval.approval_token,
                )
                raise TelegramIngestionDenied("telegram_approval_delivery_failed")
            retain_for_approval = True
        finally:
            db.close()

        _audit_context(
            job.context,
            "telegram_ingestion_pending_approval",
            {
                "job_id": job.job_id,
                "operation_id": approval.operation_id,
                "downloaded_size": downloaded_size,
                "expires_at": approval.expires_at.isoformat(),
            },
        )
    except TelegramIngestionDenied as denial:
        _audit_context(
            job.context,
            "telegram_ingestion_denied",
            {"job_id": job.job_id, "reason": denial.reason, "filename": job.filename},
        )
        _notify_context(job.token, job.context, f"❌ {denial.public_message}")
    except TelegramApprovalDenied as denial:
        _audit_context(
            job.context,
            "telegram_ingestion_approval_denied",
            {"job_id": job.job_id, "reason": denial.reason},
        )
        _notify_context(job.token, job.context, f"❌ {denial.public_message}")
    except Exception:
        logger.exception("Telegram ingestion job failed")
        try:
            _audit_context(
                job.context,
                "telegram_ingestion_failed",
                {"job_id": job.job_id, "filename": job.filename},
            )
        except Exception:
            logger.exception("Unable to audit Telegram ingestion failure")
        _notify_context(job.token, job.context, "❌ تعذر معالجة الملف بصورة آمنة.")
    finally:
        if local_path is not None and not retain_for_approval:
            local_path.unlink(missing_ok=True)


class BoundedTelegramIngestionQueue:
    """Fixed-worker, bounded queue with actor, organization, rate, and TTL limits."""

    def __init__(
        self,
        *,
        worker_count: int,
        queue_size: int,
        max_pending_per_actor: int,
        max_pending_per_organization: int,
        rate_limit: int,
        rate_window_seconds: int,
        job_ttl_seconds: int,
        processor: Processor = process_ingestion_job,
        notifier: Notifier | None = None,
        auditor: Auditor | None = None,
        now_fn: Callable[[], float] = time.monotonic,
    ):
        if worker_count < 1 or queue_size < 1:
            raise ValueError("worker_count and queue_size must be positive")
        self.worker_count = worker_count
        self.queue_size = queue_size
        self.max_pending_per_actor = max_pending_per_actor
        self.max_pending_per_organization = max_pending_per_organization
        self.rate_limit = rate_limit
        self.rate_window_seconds = rate_window_seconds
        self.job_ttl_seconds = job_ttl_seconds
        self.processor = processor
        self.notifier = notifier or self._default_notifier
        self.auditor = auditor or self._default_auditor
        self.now_fn = now_fn

        self._queue: queue.Queue[TelegramIngestionJob | None] = queue.Queue(maxsize=queue_size)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._pending_by_actor: collections.Counter[tuple[int, int]] = collections.Counter()
        self._pending_by_organization: collections.Counter[int] = collections.Counter()
        self._attempts_by_actor: dict[tuple[int, int], collections.deque[float]] = {}

    @staticmethod
    def _default_notifier(job: TelegramIngestionJob, text: str) -> None:
        _notify_context(job.token, job.context, text)

    @staticmethod
    def _default_auditor(
        job: TelegramIngestionJob,
        action: str,
        details: dict[str, Any],
    ) -> None:
        _audit_context(job.context, action, {"job_id": job.job_id, **details})

    def start(self) -> None:
        with self._lock:
            self._workers = [worker for worker in self._workers if worker.is_alive()]
            if self._workers:
                return
            self._stop_event.clear()
            for index in range(self.worker_count):
                worker = threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name=f"telegram-ingestion-worker-{index + 1}",
                )
                self._workers.append(worker)
                worker.start()

    def _rate_bucket(self, actor_key: tuple[int, int], now: float) -> collections.deque[float]:
        bucket = self._attempts_by_actor.setdefault(actor_key, collections.deque())
        cutoff = now - self.rate_window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket

    def enqueue(self, job: TelegramIngestionJob) -> int:
        self.start()
        now = self.now_fn()
        with self._lock:
            bucket = self._rate_bucket(job.actor_key, now)
            if len(bucket) >= self.rate_limit:
                raise TelegramIngestionDenied(
                    "telegram_upload_rate_limited",
                    "تم تجاوز معدل رفع الملفات المسموح. حاول لاحقًا.",
                )
            bucket.append(now)
            if self._pending_by_actor[job.actor_key] >= self.max_pending_per_actor:
                raise TelegramIngestionDenied(
                    "telegram_actor_pending_limit",
                    "لديك ملف قيد المعالجة بالفعل. انتظر اكتماله.",
                )
            if self._pending_by_organization[job.organization_id] >= self.max_pending_per_organization:
                raise TelegramIngestionDenied(
                    "telegram_organization_pending_limit",
                    "طابور المؤسسة ممتلئ مؤقتًا. حاول لاحقًا.",
                )
            try:
                self._queue.put_nowait(job)
            except queue.Full as exc:
                raise TelegramIngestionDenied(
                    "telegram_ingestion_queue_full",
                    "طابور المعالجة ممتلئ مؤقتًا. حاول لاحقًا.",
                ) from exc
            self._pending_by_actor[job.actor_key] += 1
            self._pending_by_organization[job.organization_id] += 1
            return self._queue.qsize()

    def _release(self, job: TelegramIngestionJob) -> None:
        with self._lock:
            self._pending_by_actor[job.actor_key] -= 1
            if self._pending_by_actor[job.actor_key] <= 0:
                self._pending_by_actor.pop(job.actor_key, None)
            self._pending_by_organization[job.organization_id] -= 1
            if self._pending_by_organization[job.organization_id] <= 0:
                self._pending_by_organization.pop(job.organization_id, None)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                self._queue.task_done()
                break
            try:
                age = self.now_fn() - job.submitted_monotonic
                if age > self.job_ttl_seconds:
                    self.auditor(
                        job,
                        "telegram_ingestion_queue_expired",
                        {"age_seconds": round(age, 3)},
                    )
                    self.notifier(
                        job,
                        "❌ انتهت مهلة الملف داخل الطابور. أعد إرساله.",
                    )
                else:
                    self.processor(job)
            except Exception:
                logger.exception("Unhandled Telegram ingestion worker failure")
                try:
                    self.auditor(job, "telegram_ingestion_worker_failed", {})
                    self.notifier(job, "❌ تعذر معالجة الملف بصورة آمنة.")
                except Exception:
                    logger.exception("Unable to report Telegram worker failure")
            finally:
                self._release(job)
                self._queue.task_done()

    def stop(self, *, clear_queued: bool = True) -> int:
        self._stop_event.set()
        cleared = 0
        if clear_queued:
            while True:
                try:
                    job = self._queue.get_nowait()
                except queue.Empty:
                    break
                if job is not None:
                    cleared += 1
                    try:
                        self.auditor(job, "telegram_ingestion_discarded_on_shutdown", {})
                    except Exception:
                        logger.exception("Unable to audit discarded Telegram ingestion job")
                    self._release(job)
                self._queue.task_done()
        workers = list(self._workers)
        for _ in workers:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break
        for worker in workers:
            worker.join(timeout=3)
        with self._lock:
            self._workers = [worker for worker in workers if worker.is_alive()]
        return cleared

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_depth": self._queue.qsize(),
                "queue_capacity": self.queue_size,
                "worker_count_configured": self.worker_count,
                "workers_alive": sum(1 for worker in self._workers if worker.is_alive()),
                "active_actor_count": len(self._pending_by_actor),
                "active_organization_count": len(self._pending_by_organization),
                "stopping": self._stop_event.is_set(),
            }


def build_ingestion_job(
    token: str,
    context: TelegramSecurityContext,
    *,
    file_id: Any,
    filename: Any,
    declared_size: Any,
    update_id: int | None,
    submitted_monotonic: float | None = None,
) -> TelegramIngestionJob:
    _validate_bot_token(token)
    return TelegramIngestionJob(
        job_id=uuid.uuid4().hex,
        token=token,
        context=context,
        file_id=validate_telegram_file_id(file_id),
        filename=validate_telegram_filename(filename),
        declared_size=validate_declared_file_size(declared_size),
        update_id=update_id,
        submitted_monotonic=(
            time.monotonic() if submitted_monotonic is None else submitted_monotonic
        ),
    )


_queue_lock = threading.RLock()
_global_queue: BoundedTelegramIngestionQueue | None = None


def get_ingestion_queue() -> BoundedTelegramIngestionQueue:
    global _global_queue
    with _queue_lock:
        if _global_queue is None:
            _global_queue = BoundedTelegramIngestionQueue(
                worker_count=settings.TELEGRAM_INGESTION_WORKERS,
                queue_size=settings.TELEGRAM_INGESTION_QUEUE_SIZE,
                max_pending_per_actor=settings.TELEGRAM_MAX_PENDING_PER_ACTOR,
                max_pending_per_organization=settings.TELEGRAM_MAX_PENDING_PER_ORGANIZATION,
                rate_limit=settings.TELEGRAM_UPLOAD_RATE_LIMIT,
                rate_window_seconds=settings.TELEGRAM_UPLOAD_RATE_WINDOW_SECONDS,
                job_ttl_seconds=settings.TELEGRAM_INGESTION_JOB_TTL_SECONDS,
            )
        return _global_queue


def enqueue_document_job(
    token: str,
    context: TelegramSecurityContext,
    *,
    file_id: Any,
    filename: Any,
    declared_size: Any,
    update_id: int | None,
) -> int:
    job = build_ingestion_job(
        token,
        context,
        file_id=file_id,
        filename=filename,
        declared_size=declared_size,
        update_id=update_id,
    )
    try:
        position = get_ingestion_queue().enqueue(job)
    except TelegramIngestionDenied as denial:
        _audit_context(
            context,
            "telegram_ingestion_enqueue_denied",
            {"reason": denial.reason, "filename": job.filename, "update_id": update_id},
        )
        raise
    _audit_context(
        context,
        "telegram_ingestion_queued",
        {
            "job_id": job.job_id,
            "filename": job.filename,
            "declared_size": job.declared_size,
            "queue_position": position,
            "update_id": update_id,
        },
    )
    return position


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


def _cleanup_expired_state() -> None:
    try:
        db = SessionLocal()
        try:
            expired_ids = set(expire_pending_approvals(db))
        finally:
            db.close()
        if expired_ids:
            from app.services import telegram_bot

            with telegram_bot.pending_entries_lock:
                for key, marker in list(telegram_bot.PENDING_ENTRIES.items()):
                    if marker.get("operation_id") in expired_ids:
                        telegram_bot.PENDING_ENTRIES.pop(key, None)
    except Exception:
        logger.exception("Telegram approval expiry cleanup failed")

    cutoff = time.time() - max(settings.TELEGRAM_INGESTION_JOB_TTL_SECONDS * 2, 600)
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        for pattern in ("*.part", ".*.part"):
            for candidate in UPLOAD_DIR.glob(pattern):
                try:
                    if candidate.is_file() and candidate.stat().st_mtime <= cutoff:
                        candidate.unlink(missing_ok=True)
                except OSError:
                    continue
    except OSError:
        logger.exception("Telegram partial-file cleanup failed")


def secure_polling_loop(token: str) -> None:
    """Authorized polling with no thread-per-upload behavior."""

    from app.services import telegram_bot

    logger.info("Telegram bounded polling loop started")
    get_ingestion_queue().start()
    last_update_id = 0
    last_cleanup = 0.0
    try:
        while not telegram_bot.stop_event.is_set():
            now = time.monotonic()
            if now - last_cleanup >= 30:
                _cleanup_expired_state()
                last_cleanup = now

            updates = telegram_api_request(
                token,
                "getUpdates",
                {
                    "offset": last_update_id,
                    "timeout": 20,
                    "limit": 25,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout_seconds=max(settings.TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS, 25),
            )
            if not updates or not updates.get("ok"):
                telegram_bot.stop_event.wait(3)
                continue

            for update in updates.get("result", []):
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    last_update_id = max(last_update_id, update_id + 1)

                query = update.get("callback_query")
                if isinstance(query, dict):
                    actor = query.get("from") or {}
                    message = query.get("message") or {}
                    chat = message.get("chat") or {}
                    parsed = parse_callback_data(query.get("data"))
                    callback_permissions = (
                        ("post_odoo_entries",)
                        if parsed is not None and parsed[0] == "approve"
                        else ("view_financials",)
                    )
                    try:
                        context = _authorize_update(
                            telegram_user_id=actor.get("id"),
                            telegram_chat_id=chat.get("id"),
                            chat_type=chat.get("type"),
                            required_permissions=callback_permissions,
                            event_type="callback_query",
                            update_id=update_id,
                        )
                    except TelegramAuthorizationDenied as denial:
                        callback_id = query.get("id")
                        if callback_id:
                            telegram_api_request(
                                token,
                                "answerCallbackQuery",
                                {
                                    "callback_query_id": callback_id,
                                    "text": denial.public_message,
                                    "show_alert": True,
                                },
                            )
                        continue
                    telegram_bot.handle_callback_query(token, query, context)
                    continue

                message = update.get("message")
                if not isinstance(message, dict):
                    continue
                actor = message.get("from") or {}
                chat = message.get("chat") or {}
                document = message.get("document")
                photos = message.get("photo")
                is_upload = isinstance(document, dict) or (
                    isinstance(photos, list) and bool(photos)
                )
                try:
                    context = _authorize_update(
                        telegram_user_id=actor.get("id"),
                        telegram_chat_id=chat.get("id"),
                        chat_type=chat.get("type"),
                        required_permissions=(
                            ("upload_documents", "create_entries")
                            if is_upload
                            else ("view_financials",)
                        ),
                        event_type="message_upload" if is_upload else "message",
                        update_id=update_id,
                    )
                except TelegramAuthorizationDenied as denial:
                    chat_id = chat.get("id")
                    if isinstance(chat_id, int):
                        telegram_api_request(
                            token,
                            "sendMessage",
                            {"chat_id": chat_id, "text": f"❌ {denial.public_message}"},
                        )
                    continue

                message_date = message.get("date")
                if (
                    not isinstance(message_date, (int, float))
                    or time.time() - message_date > settings.TELEGRAM_MESSAGE_MAX_AGE_SECONDS
                    or message_date - time.time() > 30
                ):
                    _audit_context(
                        context,
                        "telegram_stale_message_ignored",
                        {"update_id": update_id},
                    )
                    continue

                text = message.get("text")
                if isinstance(text, str):
                    response_text = (
                        "🤖 <b>مرحباً بك في مساعد GuardianAI المحاسبي الآمن!</b>\n\n"
                        "تم التحقق من هويتك. الملفات تمر عبر طابور محدود وفحص حجم "
                        "ومحتوى وبرمجيات ضارة قبل التحليل."
                        if text.strip().startswith("/start")
                        else "ℹ️ يرجى إرسال مستند PDF أو صورة للبدء بالتحليل."
                    )
                    payload: dict[str, Any] = {
                        "chat_id": context.telegram_chat_id,
                        "text": response_text,
                    }
                    if text.strip().startswith("/start"):
                        payload["parse_mode"] = "HTML"
                    telegram_api_request(token, "sendMessage", payload)
                    _audit_context(
                        context,
                        "telegram_text_message_handled",
                        {"command": text[:32]},
                    )
                    continue

                file_id: Any = None
                filename: Any = None
                declared_size: Any = None
                if isinstance(document, dict):
                    file_id = document.get("file_id")
                    filename = document.get("file_name")
                    declared_size = document.get("file_size")
                elif isinstance(photos, list) and photos:
                    photo = photos[-1]
                    if isinstance(photo, dict):
                        file_id = photo.get("file_id")
                        unique = str(photo.get("file_unique_id") or uuid.uuid4().hex)[:32]
                        filename = f"photo_{unique}.jpg"
                        declared_size = photo.get("file_size")

                try:
                    position = enqueue_document_job(
                        token,
                        context,
                        file_id=file_id,
                        filename=filename,
                        declared_size=declared_size,
                        update_id=update_id,
                    )
                    telegram_api_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": context.telegram_chat_id,
                            "text": f"✅ تم قبول الملف في الطابور الآمن. ترتيبه الحالي: {position}.",
                        },
                    )
                except TelegramIngestionDenied as denial:
                    telegram_api_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": context.telegram_chat_id,
                            "text": f"❌ {denial.public_message}",
                        },
                    )
    finally:
        shutdown_ingestion_queue()
        logger.info("Telegram bounded polling loop stopped")


def shutdown_ingestion_queue() -> int:
    global _global_queue
    with _queue_lock:
        manager = _global_queue
        _global_queue = None
    return manager.stop(clear_queued=True) if manager is not None else 0


def get_ingestion_status() -> dict[str, Any]:
    with _queue_lock:
        manager = _global_queue
    if manager is None:
        return {
            "queue_depth": 0,
            "queue_capacity": settings.TELEGRAM_INGESTION_QUEUE_SIZE,
            "worker_count_configured": settings.TELEGRAM_INGESTION_WORKERS,
            "workers_alive": 0,
            "active_actor_count": 0,
            "active_organization_count": 0,
            "stopping": False,
        }
    return manager.status()


def reset_ingestion_queue_for_tests() -> None:
    shutdown_ingestion_queue()
