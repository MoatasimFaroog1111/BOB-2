from __future__ import annotations

import pytest

from app.core.config import Settings


def _production_settings(**overrides):
    values = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://guardian:strong-password@db:5432/guardianai",
        "REDIS_URL": "redis://:strong-password@redis:6379/0",
        "SECRET_KEY": "x" * 64,
        "FRONTEND_ORIGIN": "https://app.example.test",
        "TRUSTED_HOSTS": "app.example.test,api.example.test",
        "TRUSTED_PROXY_IPS": "127.0.0.1/32",
        "REQUIRE_HTTPS": True,
        "REQUIRE_MALWARE_SCAN": True,
        "CLAMAV_HOST": "clamav",
        "ERP_OUTBOUND_ALLOWED_HOSTS": "odoo.example.test",
        "SECRET_STORE_PROVIDER": "azure_key_vault",
        "AZURE_KEY_VAULT_URL": "https://guardian-app.vault.azure.net",
        "ACCOUNTING_LLM_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_accepts_exact_azure_key_vault_configuration():
    settings = _production_settings()
    settings.validate_runtime_security()


@pytest.mark.parametrize("provider", ["disabled", "memory", "filesystem", "environment"])
def test_production_rejects_non_key_vault_secret_providers(provider):
    settings = _production_settings(SECRET_STORE_PROVIDER=provider)
    with pytest.raises(ValueError, match="SECRET_STORE_PROVIDER"):
        settings.validate_runtime_security()


@pytest.mark.parametrize(
    "vault_url",
    [
        "",
        "http://guardian-app.vault.azure.net",
        "https://guardian-app.vault.azure.net/path",
        "https://guardian-app.vault.azure.net?x=1",
        "https://guardian-app.vault.azure.net.evil.test",
        "https://user:pass@guardian-app.vault.azure.net",
        "https://127.0.0.1",
    ],
)
def test_production_rejects_invalid_vault_urls(vault_url):
    settings = _production_settings(AZURE_KEY_VAULT_URL=vault_url)
    with pytest.raises(ValueError, match="AZURE_KEY_VAULT_URL"):
        settings.validate_runtime_security()


def test_production_rejects_external_llm_environment_keys():
    settings = _production_settings(ACCOUNTING_LLM_API_KEY="must-not-be-here")
    with pytest.raises(ValueError, match="environment variables"):
        settings.validate_runtime_security()


def test_telegram_enablement_requires_explicit_runtime_organization():
    settings = _production_settings(
        TELEGRAM_BOT_ENABLED=True,
        TELEGRAM_BOT_PRODUCTION_READY=True,
        TELEGRAM_RUNTIME_ORGANIZATION_ID=0,
    )
    with pytest.raises(ValueError, match="TELEGRAM_RUNTIME_ORGANIZATION_ID"):
        settings.validate_runtime_security()
