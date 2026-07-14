"""Tests that production cannot start with optional security controls."""

import pytest

from app.core.config import Settings


def _production_settings(**overrides) -> Settings:
    values = {
        "APP_ENV": "production",
        "SECRET_KEY": "a" * 64,
        "DATABASE_URL": "postgresql://guardian:strong-password@db:5432/guardianai",
        "REDIS_URL": "redis://:strong-password@redis:6379/0",
        "FRONTEND_ORIGIN": "https://app.example.test",
        "TRUSTED_HOSTS": "app.example.test,api.example.test",
        "TRUSTED_PROXY_IPS": "10.0.0.10/32",
        "REQUIRE_HTTPS": True,
        "REQUIRE_MALWARE_SCAN": True,
        "CLAMAV_HOST": "clamav",
        "GUARDIAN_SEED_EMAIL": "",
        "GUARDIAN_SEED_PASSWORD": "",
        "ERP_OUTBOUND_REQUIRE_ALLOWLIST": True,
        "ERP_OUTBOUND_ALLOWED_HOSTS": "odoo.example.test",
        "ERP_OUTBOUND_ALLOWED_CIDRS": "",
        "ERP_OUTBOUND_ALLOWED_PORTS": "443",
        "ERP_OUTBOUND_ALLOW_HTTP": False,
        "LOCAL_LLM_ENABLED": False,
        "EXTERNAL_LLM_ENABLED": False,
        "EXTERNAL_LLM_REQUIRED_DPA_VERSION": "2026-07-v1",
        "EXTERNAL_LLM_ALLOWED_PROVIDERS": "deepseek",
        "EXTERNAL_LLM_ALLOWED_MODELS": "deepseek:deepseek-chat",
        "EXTERNAL_LLM_ALLOWED_HOSTS": "api.deepseek.com",
        "ACCOUNTING_LLM_API_URL": "https://api.deepseek.com/chat/completions",
        "ACCOUNTING_LLM_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_complete_production_security_configuration_is_accepted():
    settings = _production_settings()
    settings.validate_runtime_security()


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("SECRET_KEY", "short", "SECRET_KEY"),
        ("TRUSTED_HOSTS", "", "TRUSTED_HOSTS"),
        ("TRUSTED_PROXY_IPS", "", "TRUSTED_PROXY_IPS"),
        ("REQUIRE_HTTPS", False, "REQUIRE_HTTPS"),
        ("REDIS_URL", "", "REDIS_URL"),
        ("FRONTEND_ORIGIN", "http://app.example.test", "FRONTEND_ORIGIN"),
        ("DATABASE_URL", "sqlite:///./unsafe.db", "SQLite"),
        ("REQUIRE_MALWARE_SCAN", False, "REQUIRE_MALWARE_SCAN"),
        ("CLAMAV_HOST", "", "CLAMAV_HOST"),
        ("GUARDIAN_SEED_EMAIL", "owner@example.test", "owner seeding"),
        ("ERP_OUTBOUND_REQUIRE_ALLOWLIST", False, "ERP_OUTBOUND_REQUIRE_ALLOWLIST"),
        ("ERP_OUTBOUND_ALLOWED_HOSTS", "", "ERP_OUTBOUND_ALLOWED_HOSTS"),
        ("ERP_OUTBOUND_ALLOWED_HOSTS", "*", "global wildcard"),
        ("ERP_OUTBOUND_ALLOW_HTTP", True, "ERP_OUTBOUND_ALLOW_HTTP"),
        ("ERP_OUTBOUND_ALLOWED_CIDRS", "0.0.0.0/0", "private network"),
        ("LOCAL_LLM_TIMEOUT_SECONDS", 0, "LOCAL_LLM_TIMEOUT_SECONDS"),
        ("LOCAL_LLM_MAX_RESPONSE_BYTES", 1, "LOCAL_LLM_MAX_RESPONSE_BYTES"),
        ("EXTERNAL_LLM_MAX_REQUEST_BYTES", 1, "EXTERNAL_LLM_MAX_REQUEST_BYTES"),
        ("EXTERNAL_LLM_MAX_RESPONSE_BYTES", 1, "EXTERNAL_LLM_MAX_RESPONSE_BYTES"),
        ("EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS", 9000, "EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS"),
    ],
)
def test_production_rejects_missing_security_control(field, value, expected):
    settings = _production_settings(**{field: value})
    with pytest.raises(ValueError, match=expected):
        settings.validate_runtime_security()


def test_production_rejects_non_loopback_local_llm():
    settings = _production_settings(
        LOCAL_LLM_ENABLED=True,
        OLLAMA_BASE_URL="http://ollama.internal:11434",
    )
    with pytest.raises(ValueError, match="loopback-only"):
        settings.validate_runtime_security()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"ACCOUNTING_LLM_API_KEY": ""}, "API key"),
        ({"ACCOUNTING_LLM_API_KEY": "key", "EXTERNAL_LLM_ALLOWED_PROVIDERS": "*"}, "explicit allowlist"),
        ({"ACCOUNTING_LLM_API_KEY": "key", "EXTERNAL_LLM_ALLOWED_MODELS": "*"}, "explicit provider:model"),
        ({"ACCOUNTING_LLM_API_KEY": "key", "EXTERNAL_LLM_ALLOWED_HOSTS": "*"}, "exact hosts"),
        ({"ACCOUNTING_LLM_API_KEY": "key", "EXTERNAL_LLM_REQUIRED_DPA_VERSION": ""}, "DPA_VERSION"),
        (
            {
                "ACCOUNTING_LLM_API_KEY": "key",
                "ACCOUNTING_LLM_API_URL": "http://api.deepseek.com/chat/completions",
            },
            "approved HTTPS",
        ),
        (
            {
                "ACCOUNTING_LLM_API_KEY": "key",
                "ACCOUNTING_LLM_API_URL": "https://evil.example/chat/completions",
            },
            "approved HTTPS",
        ),
    ],
)
def test_production_external_llm_enablement_is_fail_closed(overrides, expected):
    settings = _production_settings(EXTERNAL_LLM_ENABLED=True, **overrides)
    with pytest.raises(ValueError, match=expected):
        settings.validate_runtime_security()


def test_production_accepts_explicit_external_llm_technical_configuration():
    settings = _production_settings(
        EXTERNAL_LLM_ENABLED=True,
        ACCOUNTING_LLM_API_KEY="technical-key-present",
    )
    settings.validate_runtime_security()


def test_production_rejects_published_database_credentials():
    settings = _production_settings(
        DATABASE_URL="postgresql://guardian:guardian@db:5432/guardianai"
    )
    with pytest.raises(ValueError, match="default database credentials"):
        settings.validate_runtime_security()


def test_production_rejects_any_seed_password():
    settings = _production_settings(GUARDIAN_SEED_PASSWORD="Unique@TestPassword123!")
    with pytest.raises(ValueError, match="owner seeding"):
        settings.validate_runtime_security()
