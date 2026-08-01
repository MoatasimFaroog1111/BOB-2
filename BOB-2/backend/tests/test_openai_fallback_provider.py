from __future__ import annotations

import socket

import pytest

from app.core.config import settings
from app.services import llm_service
from app.services.openai_fallback_provider import (
    DisabledChatProvider,
    OpenAIFallbackConfig,
    OpenAIFallbackError,
    OpenAIResponsesChatProvider,
    _extract_output_text,
    _validate_endpoint,
    build_openai_fallback_provider,
)
from app.services.openai_runtime_config import (
    TenantAwareOpenAIConfigSource,
    TenantOpenAISelection,
)


def _config(**overrides):
    values = {
        "enabled": True,
        "api_key": "test-key",
        "model": "gpt-5-mini",
        "api_url": "https://api.openai.com/v1/responses",
        "allowed_hosts": ("api.openai.com",),
        "timeout_seconds": 45,
        "max_response_bytes": 1_048_576,
        "max_output_tokens": 2_048,
    }
    values.update(overrides)
    return OpenAIFallbackConfig(**values)


class StaticConfigSource:
    def __init__(self, config):
        self.config = config

    def load(self):
        return self.config


class StaticTenantSettings:
    def __init__(self, selection):
        self.selection = selection
        self.requested_organizations = []

    def resolve(self, organization_id):
        self.requested_organizations.append(organization_id)
        return self.selection


def test_disabled_provider_returns_none_without_network():
    assert DisabledChatProvider().chat("system", "user") is None
    assert OpenAIResponsesChatProvider(_config(enabled=False)).chat("system", "user") is None


def test_extract_output_text_from_responses_api_shape():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "first"},
                    {"type": "refusal", "refusal": "ignored"},
                ],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "second"}],
            },
        ]
    }
    assert _extract_output_text(payload) == "first\nsecond"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1/responses",
        "https://evil.example/v1/responses",
        "https://user:password@api.openai.com/v1/responses",
        "https://api.openai.com:8443/v1/responses",
        "https://api.openai.com/v1/responses?redirect=x",
        "https://api.openai.com/v1/chat/completions",
    ],
)
def test_openai_endpoint_rejects_unapproved_forms(monkeypatch, url):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    with pytest.raises(OpenAIFallbackError):
        _validate_endpoint(_config(api_url=url))


def test_openai_endpoint_accepts_exact_public_host(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, _family, _socktype: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))
        ],
    )
    endpoint = _validate_endpoint(_config())
    assert endpoint.hostname == "api.openai.com"
    assert endpoint.path == "/v1/responses"
    assert endpoint.resolved_ips == ("8.8.8.8",)


def test_tenant_settings_replace_environment_key_and_model(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", True)
    tenant_settings = StaticTenantSettings(
        TenantOpenAISelection(api_key="tenant-secret", model="gpt-5.6-mini")
    )
    source = TenantAwareOpenAIConfigSource(
        deployment_source=StaticConfigSource(
            _config(api_key="environment-secret", model="environment-model")
        ),
        tenant_settings=tenant_settings,
        tenant_id_resolver=lambda: 42,
    )

    resolved = source.load()

    assert resolved.enabled is True
    assert resolved.api_key == "tenant-secret"
    assert resolved.model == "gpt-5.6-mini"
    assert tenant_settings.requested_organizations == [42]


def test_tenant_request_fails_closed_when_ui_credential_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", True)
    tenant_settings = StaticTenantSettings(None)
    source = TenantAwareOpenAIConfigSource(
        deployment_source=StaticConfigSource(_config(api_key="environment-secret")),
        tenant_settings=tenant_settings,
        tenant_id_resolver=lambda: 7,
    )

    resolved = source.load()

    assert resolved.enabled is False
    assert resolved.api_key == ""
    assert tenant_settings.requested_organizations == [7]


def test_tenant_request_respects_global_kill_switch(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", False)
    tenant_settings = StaticTenantSettings(
        TenantOpenAISelection(api_key="tenant-secret", model="gpt-5-mini")
    )
    source = TenantAwareOpenAIConfigSource(
        deployment_source=StaticConfigSource(_config(enabled=True)),
        tenant_settings=tenant_settings,
        tenant_id_resolver=lambda: 9,
    )

    resolved = source.load()

    assert resolved.enabled is False
    assert resolved.api_key == ""
    assert tenant_settings.requested_organizations == []


def test_non_tenant_background_execution_keeps_explicit_deployment_config(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", False)
    deployment = _config(api_key="background-secret", model="background-model")
    source = TenantAwareOpenAIConfigSource(
        deployment_source=StaticConfigSource(deployment),
        tenant_settings=StaticTenantSettings(None),
        tenant_id_resolver=lambda: None,
    )

    assert source.load() is deployment


def test_provider_factory_depends_on_injected_config_source():
    provider = build_openai_fallback_provider(
        StaticConfigSource(_config(enabled=False, api_key=""))
    )
    assert isinstance(provider, DisabledChatProvider)


def test_local_result_has_priority_over_secondary_provider(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_LLM_ENABLED", True)
    monkeypatch.setattr(llm_service, "_call_local_ollama", lambda *_args: "local-result")
    monkeypatch.setattr(
        llm_service,
        "build_openai_fallback_provider",
        lambda: (_ for _ in ()).throw(AssertionError("secondary provider built")),
    )
    assert llm_service.chat("system", "user") == "local-result"


def test_secondary_provider_is_used_after_local_failure(monkeypatch):
    class Secondary:
        def chat(self, system_prompt, user_prompt, temperature=0.0):
            assert system_prompt == "system"
            assert user_prompt == "user"
            assert temperature == 0.2
            return "openai-result"

    monkeypatch.setattr(settings, "LOCAL_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_service,
        "_call_local_ollama",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("ollama unavailable")),
    )
    monkeypatch.setattr(llm_service, "build_openai_fallback_provider", lambda: Secondary())
    assert llm_service.chat("system", "user", temperature=0.2) == "openai-result"
