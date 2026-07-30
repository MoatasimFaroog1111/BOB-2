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
