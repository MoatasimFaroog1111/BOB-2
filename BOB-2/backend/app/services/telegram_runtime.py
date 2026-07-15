"""Central fail-closed runtime control for the Telegram bot."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_runtime_lock = threading.RLock()
_emergency_disabled = threading.Event()
_installed = False
_original_start = None
_original_stop = None
_last_reason = "not_started"


def evaluate_runtime_policy() -> tuple[bool, str]:
    if _emergency_disabled.is_set():
        return False, "emergency_disabled"
    if not settings.TELEGRAM_BOT_ENABLED:
        return False, "disabled_by_configuration"
    if settings.is_production and not settings.TELEGRAM_BOT_PRODUCTION_READY:
        return False, "production_security_controls_incomplete"
    if settings.TELEGRAM_RUNTIME_ORGANIZATION_ID <= 0:
        return False, "runtime_organization_not_configured"
    return True, "allowed"


def _telegram_module():
    from app.services import telegram_bot

    return telegram_bot


def _audit_runtime_event(
    action: str,
    *,
    details: dict[str, Any] | None = None,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> None:
    try:
        from app.db.database import SessionLocal
        from app.models.core import AuditLog

        db = SessionLocal()
        try:
            target_org = organization_id or settings.TELEGRAM_RUNTIME_ORGANIZATION_ID or None
            db.add(
                AuditLog(
                    organization_id=target_org,
                    user_id=user_id,
                    action=action,
                    entity_type="telegram_runtime",
                    entity_id=str(target_org or "disabled"),
                    details=details or {},
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to persist Telegram runtime audit event: %s", action)


def install_runtime_guard() -> None:
    global _installed, _original_start, _original_stop
    with _runtime_lock:
        if _installed:
            return
        module = _telegram_module()
        _original_start = module.start_telegram_bot
        _original_stop = module.stop_telegram_bot
        module.start_telegram_bot = start_telegram_bot
        module.stop_telegram_bot = stop_telegram_bot
        _installed = True
        logger.info("Telegram runtime guard installed")


def _clear_pending_entries(reason: str) -> int:
    module = _telegram_module()
    local_count = len(module.PENDING_ENTRIES)
    module.PENDING_ENTRIES.clear()
    try:
        from app.db.database import SessionLocal
        from app.services.telegram_accounting_service import revoke_all_pending_operations

        db = SessionLocal()
        try:
            durable_count = revoke_all_pending_operations(db, reason=reason)
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to revoke durable Telegram approvals")
        durable_count = 0
    return max(local_count, durable_count)


def _pending_count() -> int:
    try:
        from app.db.database import SessionLocal
        from app.services.telegram_accounting_service import count_pending_operations

        db = SessionLocal()
        try:
            return count_pending_operations(db)
        finally:
            db.close()
    except Exception:
        return len(_telegram_module().PENDING_ENTRIES)


def _ingestion_status() -> dict[str, Any]:
    try:
        from app.services.telegram_ingestion import get_ingestion_status

        return get_ingestion_status()
    except Exception:
        logger.exception("Failed to read Telegram ingestion status")
        return {
            "queue_depth": 0,
            "queue_capacity": settings.TELEGRAM_INGESTION_QUEUE_SIZE,
            "worker_count_configured": settings.TELEGRAM_INGESTION_WORKERS,
            "workers_alive": 0,
            "active_actor_count": 0,
            "active_organization_count": 0,
            "stopping": True,
        }


def is_running() -> bool:
    module = _telegram_module()
    thread = module.bot_thread
    return bool(thread and thread.is_alive())


def start_telegram_bot() -> bool:
    global _last_reason
    install_runtime_guard()
    allowed, reason = evaluate_runtime_policy()
    if not allowed:
        _last_reason = reason
        stop_telegram_bot(reason=reason, audit_event=False)
        logger.warning("Telegram bot start refused: %s", reason)
        _audit_runtime_event(
            "telegram_bot_start_blocked",
            details={"reason": reason, "environment": settings.APP_ENV},
        )
        return False

    with _runtime_lock:
        assert _original_start is not None
        _original_start()
        running = is_running()
        _last_reason = "running" if running else "no_active_tenant_token"

    _audit_runtime_event(
        "telegram_bot_started" if running else "telegram_bot_start_skipped",
        details={
            "reason": _last_reason,
            "environment": settings.APP_ENV,
            "runtime_organization_id": settings.TELEGRAM_RUNTIME_ORGANIZATION_ID,
            "ingestion": _ingestion_status(),
        },
    )
    return running


def stop_telegram_bot(
    *,
    reason: str = "requested_stop",
    audit_event: bool = True,
) -> bool:
    """Stop polling, clear queued ingestion, and revoke outstanding approvals."""

    global _last_reason
    install_runtime_guard()
    with _runtime_lock:
        was_running = is_running()
        assert _original_stop is not None
        _original_stop()
        try:
            from app.services.telegram_ingestion import shutdown_ingestion_queue

            queued_cleared = shutdown_ingestion_queue()
        except Exception:
            logger.exception("Failed to stop Telegram ingestion queue")
            queued_cleared = 0
        pending_cleared = _clear_pending_entries(reason)
        _last_reason = reason

    if audit_event:
        _audit_runtime_event(
            "telegram_bot_stopped",
            details={
                "reason": reason,
                "was_running": was_running,
                "pending_entries_cleared": pending_cleared,
                "queued_ingestion_jobs_cleared": queued_cleared,
            },
        )
    return was_running


def emergency_disable_telegram_bot() -> dict[str, Any]:
    _emergency_disabled.set()
    stop_telegram_bot(reason="emergency_disabled", audit_event=False)
    return get_runtime_status()


def get_runtime_status(organization_id: int | None = None) -> dict[str, Any]:
    install_runtime_guard()
    module = _telegram_module()
    allowed, policy_reason = evaluate_runtime_policy()
    target_org = organization_id or settings.TELEGRAM_RUNTIME_ORGANIZATION_ID
    try:
        token_configured = bool(module.get_telegram_token(target_org)) if target_org > 0 else False
    except Exception:
        token_configured = False
    ingestion = _ingestion_status()

    return {
        "environment": settings.APP_ENV,
        "enabled_by_configuration": settings.TELEGRAM_BOT_ENABLED,
        "production_ready": settings.TELEGRAM_BOT_PRODUCTION_READY,
        "runtime_organization_id": settings.TELEGRAM_RUNTIME_ORGANIZATION_ID,
        "requested_organization_id": target_org or None,
        "emergency_disabled": _emergency_disabled.is_set(),
        "runtime_allowed": allowed,
        "running": is_running(),
        "token_configured": token_configured,
        "pending_entries": _pending_count(),
        "approval_ttl_seconds": settings.TELEGRAM_APPROVAL_TTL_SECONDS,
        "ingestion_queue_depth": ingestion["queue_depth"],
        "ingestion_queue_capacity": ingestion["queue_capacity"],
        "ingestion_workers_configured": ingestion["worker_count_configured"],
        "ingestion_workers_alive": ingestion["workers_alive"],
        "ingestion_active_actors": ingestion["active_actor_count"],
        "ingestion_active_organizations": ingestion["active_organization_count"],
        "policy_reason": policy_reason,
        "last_runtime_reason": _last_reason,
    }


def reset_emergency_disable_for_tests() -> None:
    if settings.is_production:
        raise RuntimeError("Emergency disable cannot be reset through application code in production")
    try:
        from app.services.telegram_ingestion import reset_ingestion_queue_for_tests

        reset_ingestion_queue_for_tests()
    finally:
        _emergency_disabled.clear()
