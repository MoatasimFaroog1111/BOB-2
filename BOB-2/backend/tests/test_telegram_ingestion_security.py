"""Regression tests for bounded Telegram file ingestion and cleanup."""

from __future__ import annotations

import io
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.core import (
    AuditLog,
    Organization,
    TelegramApprovalOperation,
    TelegramAuthorization,
    User,
)
from app.security.auth import hash_password
from app.services import telegram_bot
from app.services.telegram_approval_cleanup import expire_pending_approvals
from app.services.telegram_ingestion import (
    BoundedTelegramIngestionQueue,
    TelegramIngestionDenied,
    TelegramIngestionJob,
    bounded_download_telegram_file,
    build_ingestion_job,
    telegram_api_request,
    validate_declared_file_size,
    validate_telegram_remote_path,
)
from app.services.telegram_security import TelegramSecurityContext

TOKEN = "123456:abcdefghijklmnopqrstuvwxyzABCD_1234567890"


class FakeResponse:
    def __init__(self, body: bytes, *, url: str, headers: dict[str, str] | None = None):
        self._stream = io.BytesIO(body)
        self._url = url
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _context(
    *,
    telegram_user_id: int = 1001,
    telegram_chat_id: int = 1001,
    organization_id: int = 1,
    system_user_id: int = 1,
) -> TelegramSecurityContext:
    return TelegramSecurityContext(
        authorization_id=1,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        chat_type="private",
        organization_id=organization_id,
        system_user_id=system_user_id,
        system_user_email=f"user{system_user_id}@example.com",
        system_user_role="owner",
    )


def _job(
    *,
    context: TelegramSecurityContext | None = None,
    submitted: float = 0.0,
    suffix: str = "a",
) -> TelegramIngestionJob:
    return TelegramIngestionJob(
        job_id=f"job-{suffix}",
        token=TOKEN,
        context=context or _context(),
        file_id=f"AbCdEfGhIjKlMnOp{suffix}",
        filename=f"invoice-{suffix}.pdf",
        declared_size=100,
        update_id=1,
        submitted_monotonic=submitted,
    )


def test_remote_path_rejects_urls_traversal_and_windows_paths():
    assert validate_telegram_remote_path("documents/file_1.pdf") == "documents/file_1.pdf"
    for unsafe in (
        "../secret.pdf",
        "documents/../../secret.pdf",
        "/etc/passwd",
        "https://evil.example/file.pdf",
        "documents\\file.pdf",
        "documents//file.pdf",
        "documents/%2e%2e/file.pdf",
    ):
        with pytest.raises(TelegramIngestionDenied):
            validate_telegram_remote_path(unsafe)


def test_declared_size_is_required_before_queueing(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    for invalid in (None, 0, -1, True, "100"):
        with pytest.raises(TelegramIngestionDenied) as exc:
            validate_declared_file_size(invalid)
        assert exc.value.reason == "telegram_file_size_missing"
    with pytest.raises(TelegramIngestionDenied) as oversized:
        validate_declared_file_size(1_048_577)
    assert oversized.value.reason == "telegram_file_too_large"


def test_job_validation_rejects_unsafe_extension_and_invalid_file_id(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    with pytest.raises(TelegramIngestionDenied):
        build_ingestion_job(
            TOKEN,
            _context(),
            file_id="bad/id",
            filename="invoice.pdf",
            declared_size=100,
            update_id=1,
        )
    with pytest.raises(TelegramIngestionDenied) as extension:
        build_ingestion_job(
            TOKEN,
            _context(),
            file_id="AbCdEfGhIjKlMnOp",
            filename="payload.exe",
            declared_size=100,
            update_id=1,
        )
    assert extension.value.reason == "telegram_extension_rejected"


def test_api_response_is_bounded_and_redirect_host_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_API_RESPONSE_MAX_BYTES", 64)

    def evil_opener(_request, timeout):
        assert timeout > 0
        return FakeResponse(
            b'{"ok":true}',
            url="https://evil.example/bot123/getFile",
            headers={"Content-Length": "11"},
        )

    with pytest.raises(TelegramIngestionDenied) as redirect:
        telegram_api_request(TOKEN, "getFile", {"file_id": "x"}, opener=evil_opener)
    assert redirect.value.reason == "telegram_redirect_host_rejected"

    def huge_opener(_request, timeout):
        assert timeout > 0
        return FakeResponse(
            b"x" * 65,
            url=f"https://api.telegram.org/bot{TOKEN}/getFile",
            headers={},
        )

    with pytest.raises(TelegramIngestionDenied) as huge:
        telegram_api_request(TOKEN, "getFile", {"file_id": "x"}, opener=huge_opener)
    assert huge.value.reason == "telegram_api_response_too_large"


def test_bounded_download_rejects_redirect_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr("app.services.telegram_ingestion.UPLOAD_DIR", tmp_path)
    destination = tmp_path / "safe.pdf"

    def opener(_request, timeout):
        assert timeout > 0
        return FakeResponse(
            b"abcd",
            url="https://evil.example/file.pdf",
            headers={"Content-Length": "4"},
        )

    with pytest.raises(TelegramIngestionDenied) as exc:
        bounded_download_telegram_file(
            TOKEN,
            "documents/file_1.pdf",
            destination,
            expected_size=4,
            opener=opener,
        )
    assert exc.value.reason == "telegram_redirect_host_rejected"
    assert not destination.exists()
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob(".*.part"))


def test_bounded_download_aborts_stream_over_declared_size_and_cleans_part(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(settings, "TELEGRAM_DOWNLOAD_CHUNK_SIZE_BYTES", 2)
    monkeypatch.setattr("app.services.telegram_ingestion.UPLOAD_DIR", tmp_path)
    destination = tmp_path / "safe.pdf"

    def opener(_request, timeout):
        assert timeout > 0
        return FakeResponse(
            b"abcde",
            url=f"https://api.telegram.org/file/bot{TOKEN}/documents/file_1.pdf",
            headers={},
        )

    with pytest.raises(TelegramIngestionDenied) as exc:
        bounded_download_telegram_file(
            TOKEN,
            "documents/file_1.pdf",
            destination,
            expected_size=4,
            opener=opener,
        )
    assert exc.value.reason == "telegram_download_stream_limit_exceeded"
    assert not destination.exists()
    assert not list(tmp_path.iterdir())


def test_bounded_download_writes_atomically_with_exact_size(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(settings, "TELEGRAM_DOWNLOAD_CHUNK_SIZE_BYTES", 3)
    monkeypatch.setattr("app.services.telegram_ingestion.UPLOAD_DIR", tmp_path)
    destination = tmp_path / "safe.pdf"
    body = b"%PDF-test"

    def opener(_request, timeout):
        assert timeout > 0
        return FakeResponse(
            body,
            url=f"https://api.telegram.org/file/bot{TOKEN}/documents/file_1.pdf",
            headers={"Content-Length": str(len(body))},
        )

    written = bounded_download_telegram_file(
        TOKEN,
        "documents/file_1.pdf",
        destination,
        expected_size=len(body),
        opener=opener,
    )
    assert written == len(body)
    assert destination.read_bytes() == body
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob(".*.part"))


def test_queue_enforces_actor_and_organization_pending_limits():
    started = threading.Event()
    release = threading.Event()

    def processor(_job):
        started.set()
        release.wait(timeout=3)

    manager = BoundedTelegramIngestionQueue(
        worker_count=1,
        queue_size=4,
        max_pending_per_actor=1,
        max_pending_per_organization=1,
        rate_limit=10,
        rate_window_seconds=60,
        job_ttl_seconds=300,
        processor=processor,
        notifier=lambda *_: None,
        auditor=lambda *_: None,
        now_fn=lambda: 10.0,
    )
    try:
        manager.enqueue(_job(submitted=10.0, suffix="a"))
        assert started.wait(timeout=2)
        with pytest.raises(TelegramIngestionDenied) as actor_limit:
            manager.enqueue(_job(submitted=10.0, suffix="b"))
        assert actor_limit.value.reason == "telegram_actor_pending_limit"

        other_actor = _context(telegram_user_id=2002, telegram_chat_id=2002)
        with pytest.raises(TelegramIngestionDenied) as org_limit:
            manager.enqueue(_job(context=other_actor, submitted=10.0, suffix="c"))
        assert org_limit.value.reason == "telegram_organization_pending_limit"
    finally:
        release.set()
        manager.stop()


def test_queue_enforces_fixed_capacity_and_rate_limit():
    started = threading.Event()
    release = threading.Event()

    def processor(_job):
        started.set()
        release.wait(timeout=3)

    manager = BoundedTelegramIngestionQueue(
        worker_count=1,
        queue_size=1,
        max_pending_per_actor=5,
        max_pending_per_organization=5,
        rate_limit=2,
        rate_window_seconds=60,
        job_ttl_seconds=300,
        processor=processor,
        notifier=lambda *_: None,
        auditor=lambda *_: None,
        now_fn=lambda: 10.0,
    )
    try:
        manager.enqueue(_job(submitted=10.0, suffix="a"))
        assert started.wait(timeout=2), "first job must be owned by the fixed worker"
        second_context = _context(
            telegram_user_id=2002,
            telegram_chat_id=2002,
            organization_id=2,
            system_user_id=2,
        )
        manager.enqueue(_job(context=second_context, submitted=10.0, suffix="b"))
        third_context = _context(
            telegram_user_id=3003,
            telegram_chat_id=3003,
            organization_id=3,
            system_user_id=3,
        )
        with pytest.raises(TelegramIngestionDenied) as queue_full:
            manager.enqueue(_job(context=third_context, submitted=10.0, suffix="c"))
        assert queue_full.value.reason == "telegram_ingestion_queue_full"
    finally:
        release.set()
        manager.stop()

    manager = BoundedTelegramIngestionQueue(
        worker_count=1,
        queue_size=4,
        max_pending_per_actor=4,
        max_pending_per_organization=4,
        rate_limit=2,
        rate_window_seconds=60,
        job_ttl_seconds=300,
        processor=lambda _job: time.sleep(0.2),
        notifier=lambda *_: None,
        auditor=lambda *_: None,
        now_fn=lambda: 20.0,
    )
    try:
        manager.enqueue(_job(submitted=20.0, suffix="d"))
        manager.enqueue(_job(submitted=20.0, suffix="e"))
        with pytest.raises(TelegramIngestionDenied) as rate:
            manager.enqueue(_job(submitted=20.0, suffix="f"))
        assert rate.value.reason == "telegram_upload_rate_limited"
    finally:
        manager.stop()


def test_expired_queue_job_is_not_processed_and_limits_are_released():
    processed: list[str] = []
    notified: list[str] = []
    audited: list[str] = []
    completed = threading.Event()

    def notifier(_job, text):
        notified.append(text)
        completed.set()

    manager = BoundedTelegramIngestionQueue(
        worker_count=1,
        queue_size=2,
        max_pending_per_actor=1,
        max_pending_per_organization=2,
        rate_limit=10,
        rate_window_seconds=60,
        job_ttl_seconds=30,
        processor=lambda job: processed.append(job.job_id),
        notifier=notifier,
        auditor=lambda _job, action, _details: audited.append(action),
        now_fn=lambda: 100.0,
    )
    try:
        manager.enqueue(_job(submitted=0.0, suffix="expired"))
        assert completed.wait(timeout=2)
        assert processed == []
        assert audited == ["telegram_ingestion_queue_expired"]
        assert notified
        deadline = time.time() + 2
        while manager.status()["active_actor_count"] and time.time() < deadline:
            time.sleep(0.01)
        assert manager.status()["active_actor_count"] == 0
    finally:
        manager.stop()


def test_worker_failure_releases_actor_limit():
    failed = threading.Event()

    def processor(_job):
        failed.set()
        raise RuntimeError("parser failed")

    manager = BoundedTelegramIngestionQueue(
        worker_count=1,
        queue_size=2,
        max_pending_per_actor=1,
        max_pending_per_organization=2,
        rate_limit=10,
        rate_window_seconds=60,
        job_ttl_seconds=300,
        processor=processor,
        notifier=lambda *_: None,
        auditor=lambda *_: None,
        now_fn=lambda: 10.0,
    )
    try:
        manager.enqueue(_job(submitted=10.0, suffix="a"))
        assert failed.wait(timeout=2)
        deadline = time.time() + 2
        while manager.status()["active_actor_count"] and time.time() < deadline:
            time.sleep(0.01)
        assert manager.status()["active_actor_count"] == 0
        manager.enqueue(_job(submitted=10.0, suffix="b"))
    finally:
        manager.stop()


def test_queue_starts_only_configured_worker_count():
    release = threading.Event()
    manager = BoundedTelegramIngestionQueue(
        worker_count=2,
        queue_size=4,
        max_pending_per_actor=2,
        max_pending_per_organization=4,
        rate_limit=10,
        rate_window_seconds=60,
        job_ttl_seconds=300,
        processor=lambda _job: release.wait(timeout=2),
        notifier=lambda *_: None,
        auditor=lambda *_: None,
    )
    try:
        manager.start()
        manager.start()
        status = manager.status()
        assert status["workers_alive"] == 2
        assert status["worker_count_configured"] == 2
    finally:
        release.set()
        manager.stop()


def test_legacy_direct_download_and_processing_fail_closed():
    with pytest.raises(RuntimeError):
        telegram_bot.download_file(TOKEN, "documents/file.pdf", Path("unsafe.pdf"))
    with pytest.raises(RuntimeError):
        telegram_bot.process_document(TOKEN, _context(), "file-id", "file.pdf")


def test_expired_approval_cleanup_updates_state_audits_and_deletes_file(db, tmp_path):
    organization = Organization(
        id=1,
        name="Test Org",
        legal_name="Test Org",
        country="SA",
        is_active=True,
    )
    user = User(
        id=1,
        organization_id=1,
        email="owner@example.com",
        full_name="Owner",
        role="owner",
        hashed_password=hash_password("Test@Pass1234!"),
        is_active=True,
    )
    db.add_all([organization, user])
    db.commit()
    authorization = TelegramAuthorization(
        id=1,
        telegram_user_id=1001,
        telegram_chat_id=1001,
        organization_id=1,
        system_user_id=1,
        created_by_user_id=1,
        allow_group_chats=False,
        is_active=True,
    )
    db.add(authorization)
    db.commit()

    retained = tmp_path / "retained.pdf"
    retained.write_bytes(b"%PDF-test")
    expired_at = datetime.utcnow() - timedelta(seconds=1)
    operation = TelegramApprovalOperation(
        organization_id=1,
        authorization_id=1,
        telegram_user_id=1001,
        telegram_chat_id=1001,
        system_user_id=1,
        source="telegram",
        status="pending",
        content_hash="a" * 64,
        approval_token_hash="b" * 64,
        payload={"filename": "retained.pdf"},
        file_path=str(retained),
        expires_at=expired_at,
    )
    db.add(operation)
    db.commit()
    db.refresh(operation)

    expired_ids = expire_pending_approvals(db, now=datetime.utcnow())
    db.refresh(operation)
    assert expired_ids == [operation.id]
    assert operation.status == "expired"
    assert operation.failure_code == "approval_expired_background_cleanup"
    assert not retained.exists()
    assert (
        db.query(AuditLog)
        .filter(AuditLog.action == "telegram_approval_expired_background")
        .count()
        == 1
    )


def test_bot_source_contains_no_unbounded_or_thread_per_upload_path():
    source = Path(telegram_bot.__file__).read_text(encoding="utf-8")
    assert "urlretrieve" not in source
    assert "target=process_document" not in source
    assert "Direct Telegram download is disabled" in source
