from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.core.config import settings
from app.services.openai_runtime_config import SqlAlchemyTenantOpenAISettingsResolver


def _policy(*, purposes):
    return SimpleNamespace(
        external_llm_enabled=True,
        approved_provider="openai",
        approved_model="gpt-5-mini",
        allowed_purposes=purposes,
        dpa_version="2026-07-v1",
        dpa_reference="DPA-001",
        data_residency_region="KSA",
        provider_retention_mode="contractual_zero_retention",
        accepted_at=datetime(2026, 8, 1),
        accepted_by_user_id=1,
        revoked_at=None,
    )


def _configure_openai_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_PROVIDERS", "openai")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_MODELS", "openai:gpt-5-mini")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_REQUIRED_DPA_VERSION", "2026-07-v1")


def test_accounting_reasoning_purpose_authorizes_local_first_fallback(monkeypatch):
    _configure_openai_allowlist(monkeypatch)

    assert SqlAlchemyTenantOpenAISettingsResolver._is_authorized(
        _policy(purposes=["accounting_reasoning"])
    )


def test_other_purpose_does_not_broaden_local_first_fallback(monkeypatch):
    _configure_openai_allowlist(monkeypatch)

    assert not SqlAlchemyTenantOpenAISettingsResolver._is_authorized(
        _policy(purposes=["natural_language_intent"])
    )
