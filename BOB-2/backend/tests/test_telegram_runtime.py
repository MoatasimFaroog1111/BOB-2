"""Regression tests for the centralized Telegram runtime gate."""

from app.core.config import settings
from app.models.core import AuditLog
from app.services import telegram_runtime


def test_telegram_runtime_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_ENABLED", False)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_PRODUCTION_READY", False)
    telegram_runtime.reset_emergency_disable_for_tests()

    allowed, reason = telegram_runtime.evaluate_runtime_policy()

    assert allowed is False
    assert reason == "disabled_by_configuration"


def test_production_refuses_telegram_until_security_ready(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_PRODUCTION_READY", False)

    allowed, reason = telegram_runtime.evaluate_runtime_policy()

    assert allowed is False
    assert reason == "production_security_controls_incomplete"


def test_legacy_start_entry_point_cannot_bypass_gate(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_ENABLED", False)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_PRODUCTION_READY", False)
    telegram_runtime.reset_emergency_disable_for_tests()
    telegram_runtime.install_runtime_guard()

    from app.services import telegram_bot

    assert telegram_bot.start_telegram_bot() is False
    assert telegram_runtime.get_runtime_status()["running"] is False


def test_runtime_status_requires_authentication(client):
    response = client.get("/api/v1/telegram/runtime-status")
    assert response.status_code == 401


def test_admin_status_contains_no_secret_and_emergency_stop_is_audited(
    client,
    auth_headers,
    db,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_ENABLED", False)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_PRODUCTION_READY", False)
    telegram_runtime.reset_emergency_disable_for_tests()

    status_response = client.get(
        "/api/v1/telegram/runtime-status",
        headers=auth_headers,
    )
    assert status_response.status_code == 200, status_response.text
    status_body = status_response.json()
    assert "token" not in status_body
    assert "masked_token" not in status_body
    assert "encrypted_token" not in status_body
    assert status_body["token_configured"] is False
    assert status_body["running"] is False

    disable_response = client.post(
        "/api/v1/telegram/emergency-disable",
        headers=auth_headers,
    )
    assert disable_response.status_code == 200, disable_response.text
    disable_body = disable_response.json()
    assert disable_body["emergency_disabled"] is True
    assert disable_body["running"] is False
    assert disable_body["pending_entries"] == 0

    audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "telegram_bot_emergency_disabled")
        .first()
    )
    assert audit is not None
    assert audit.organization_id == 1
    assert audit.user_id == 1
