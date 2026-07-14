"""Central fail-closed runtime control for the legacy Telegram bot.

The legacy bot is intentionally disabled by default.  Production execution requires
both an explicit enable flag and a separate readiness flag that will only be set after
the remaining Telegram authorization, approval, storage, and queue controls are in
place.  This module also patches the legacy start/stop entry points so older API code
cannot bypass the central policy.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
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
    """Return whether Telegram execution is allowed and the governing reason."""
    if _emergency_disabled.is_set():
        return False, "emergency_disabled"
    if not settings.TELEGRAM_BOT_ENABLED:
        return False, "disabled_by_configuration"
    if settings.is_production and not settings.TELEGRAM_BOT_PRODUCTION_READY:
        return False, "production_security_controls_incomplete"
    return True, "allowed"


def _telegram_module():
    from app.services import telegram_bot

    return telegram_bot


def _set_legacy_config_active(is_active: bool) -> None:
    """Keep the legacy UI state aligned with the real runtime state.

    This compatibility write is temporary until Telegram configuration is migrated to
    the organization-scoped database model in the next remediation stage.
    """
    try:
        module = _telegram_module()
        path = module.CONFIG_PATH
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["is_active"] = bool(is_active)
        data["runtime_updated_at"] = datetime.now(timezone.utc).isoformat()
        temp_path = path.with_suffix(".runtime.tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        logger.exception("Failed to synchronize legacy Telegram runtime state")


def _audit_runtime_event(
    action: str,
    *,
    details: dict[str, Any] | None = None,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> None:
    """Best-effort centralized audit event for automatic runtime transitions."""
    try:
        from app.db.database import SessionLocal
        from app.models.core import AuditLog

        db = SessionLocal()
        try:
            db.add(
                AuditLog(
                    organization_id=organization_id,
                    user_id=user_id,
                    action=action,
                    entity_type="telegram_runtime",
                    entity_id="singleton",
                    details=details or {},
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to persist Telegram runtime audit event: %s", action)


def install_runtime_guard() -> None:
    """Patch every legacy Telegram start/stop import through this policy gate."""
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


def _clear_pending_entries() -> int:
    module = _telegram_module()
    pending_count = len(module.PENDING_ENTRIES)
    module.PENDING_ENTRIES.clear()
    return pending_count


def is_running() -> bool:
    module = _telegram_module()
    thread = module.bot_thread
    return bool(thread and thread.is_alive())


def start_telegram_bot() -> bool:
    """Start the bot only when the central fail-closed policy permits it."""
    global _last_reason
    install_runtime_guard()
    allowed, reason = evaluate_runtime_policy()
    if not allowed:
        _last_reason = reason
        _set_legacy_config_active(False)
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
        _last_reason = "running" if running else "no_active_token"
        _set_legacy_config_active(running)

    _audit_runtime_event(
        "telegram_bot_started" if running else "telegram_bot_start_skipped",
        details={"reason": _last_reason, "environment": settings.APP_ENV},
    )
    return running


def stop_telegram_bot(
    *,
    reason: str = "requested_stop",
    audit_event: bool = True,
) -> bool:
    """Stop polling and clear all in-memory approvals/pending work."""
    global _last_reason
    install_runtime_guard()
    with _runtime_lock:
        was_running = is_running()
        assert _original_stop is not None
        _original_stop()
        pending_cleared = _clear_pending_entries()
        _set_legacy_config_active(False)
        _last_reason = reason

    if audit_event:
        _audit_runtime_event(
            "telegram_bot_stopped",
            details={
                "reason": reason,
                "was_running": was_running,
                "pending_entries_cleared": pending_cleared,
            },
        )
    return was_running


def emergency_disable_telegram_bot() -> dict[str, Any]:
    """Immediately disable runtime execution until the application restarts."""
    _emergency_disabled.set()
    stop_telegram_bot(reason="emergency_disabled", audit_event=False)
    return get_runtime_status()


def get_runtime_status() -> dict[str, Any]:
    """Return administrative state without exposing any token or secret."""
    install_runtime_guard()
    module = _telegram_module()
    allowed, policy_reason = evaluate_runtime_policy()
    try:
        token_configured = bool(module.get_telegram_token())
    except Exception:
        token_configured = False

    return {
        "environment": settings.APP_ENV,
        "enabled_by_configuration": settings.TELEGRAM_BOT_ENABLED,
        "production_ready": settings.TELEGRAM_BOT_PRODUCTION_READY,
        "emergency_disabled": _emergency_disabled.is_set(),
        "runtime_allowed": allowed,
        "running": is_running(),
        "token_configured": token_configured,
        "pending_entries": len(module.PENDING_ENTRIES),
        "policy_reason": policy_reason,
        "last_runtime_reason": _last_reason,
    }


def reset_emergency_disable_for_tests() -> None:
    """Test-only helper; production code intentionally exposes no re-enable endpoint."""
    if settings.is_production:
        raise RuntimeError("Emergency disable cannot be reset through application code in production")
    _emergency_disabled.clear()
