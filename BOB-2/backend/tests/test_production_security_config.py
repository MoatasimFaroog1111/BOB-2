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
        "SECRET_STORE_PROVIDER": "azure_key_vault",
        "AZURE_KEY_VAULT_URL": "https://guardian-production.vault.azure.net",
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
        ("SECRET_STORE_PROVIDER", "memory", "SECRET_STORE_PROVIDER"),
        ("AZURE_KEY_VAULT_URL", "http://guardian-production.vault.azure.net", "AZURE_KEY_VAULT_URL"),
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
        ("ACCOUNTING_LLM_API_KEY", "forbidden-environment-value", "environment variables"),
        ("DEEPSEEK_API_KEY", "forbidden-environment-value", "environment variables"),
    ],
)
def test_production_rejects_missing_security_control(field, value, expected):
    settings = _production_settings(**{field: value})
    with pytest.raises(ValueError, match=expected):
        settings.validate_runtime_security()


def test_railway_without_production_env_refuses_startup(monkeypatch):
    from app import main as main_module

    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setattr(main_module.settings, "APP_ENV", "local")

    with pytest.raises(ValueError, match="APP_ENV=production"):
        main_module._validate_startup_security()


def test_railway_without_redis_refuses_startup(monkeypatch):
    from app import main as main_module

    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "railway-production")
    monkeypatch.setattr(main_module, "settings", _production_settings(REDIS_URL=""))

    with pytest.raises(ValueError, match="REDIS_URL"):
        main_module._validate_startup_security()


def test_railway_only_delegates_managed_edge_and_temporary_clamav_controls():
    from app import main as main_module

    assert main_module._RAILWAY_DELEGATED_SECURITY_ERRORS == {
        "TRUSTED_HOSTS is required",
        "TRUSTED_PROXY_IPS is required",
        "REQUIRE_HTTPS must be true",
        "FRONTEND_ORIGIN must use https",
        "REQUIRE_MALWARE_SCAN must be true",
        "CLAMAV_HOST is required when malware scanning is enabled",
    }


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
        ({"EXTERNAL_LLM_ALLOWED_PROVIDERS": "*"}, "explicit allowlist"),
        ({"EXTERNAL_LLM_ALLOWED_MODELS": "*"}, "explicit provider:model"),
        ({"EXTERNAL_LLM_ALLOWED_HOSTS": "*"}, "exact hosts"),
        ({"EXTERNAL_LLM_REQUIRED_DPA_VERSION": ""}, "DPA_VERSION"),
        (
            {"ACCOUNTING_LLM_API_URL": "http://api.deepseek.com/chat/completions"},
            "approved HTTPS",
        ),
        (
            {"ACCOUNTING_LLM_API_URL": "https://evil.example/chat/completions"},
            "approved HTTPS",
        ),
        ({"SECRET_STORE_PROVIDER": "disabled"}, "Azure Key Vault"),
    ],
)
def test_production_external_llm_enablement_is_fail_closed(overrides, expected):
    settings = _production_settings(EXTERNAL_LLM_ENABLED=True, **overrides)
    with pytest.raises(ValueError, match=expected):
        settings.validate_runtime_security()


def test_production_accepts_external_llm_without_environment_credential():
    settings = _production_settings(EXTERNAL_LLM_ENABLED=True)
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