from __future__ import annotations

import pytest

from app.services.external_llm_provider_adapters import get_external_llm_provider_adapter


@pytest.mark.parametrize(
    ("provider", "model", "expected_url"),
    [
        ("openai", "gpt-5.6-sol", "https://api.openai.com/v1/responses"),
        ("anthropic", "claude-sonnet-5", "https://api.anthropic.com/v1/messages"),
        (
            "google",
            "gemini-3.6-flash",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent",
        ),
        ("xai", "grok-4.5", "https://api.x.ai/v1/chat/completions"),
    ],
)
def test_provider_default_urls(provider, model, expected_url):
    adapter = get_external_llm_provider_adapter(provider)
    assert adapter.default_url(model) == expected_url


def test_openai_adapter_builds_responses_request_and_normalizes_output():
    adapter = get_external_llm_provider_adapter("openai")
    request = adapter.build_request(
        model="gpt-5.6-sol",
        system_prompt="Return JSON only",
        user_content='{"safe":true}',
        max_output_tokens=1024,
        temperature=0.1,
        api_key="openai-secret",
    )
    assert request.payload["model"] == "gpt-5.6-sol"
    assert request.payload["instructions"] == "Return JSON only"
    assert "temperature" not in request.payload
    assert request.headers["Authorization"] == "Bearer openai-secret"
    normalized = adapter.normalize_response(
        {"output": [{"content": [{"type": "output_text", "text": '{"summary":"ok"}'}]}]}
    )
    assert normalized["content"][0]["text"] == '{"summary":"ok"}'


def test_anthropic_adapter_omits_sampling_controls_for_claude_5():
    adapter = get_external_llm_provider_adapter("anthropic")
    request = adapter.build_request(
        model="claude-sonnet-5",
        system_prompt="system",
        user_content="user",
        max_output_tokens=1024,
        temperature=0.1,
        api_key="anthropic-secret",
    )
    assert request.payload["model"] == "claude-sonnet-5"
    assert "temperature" not in request.payload
    assert request.headers["x-api-key"] == "anthropic-secret"
    assert adapter.normalize_response({"content": [{"type": "text", "text": "ok"}]})["content"][0]["text"] == "ok"


def test_google_adapter_uses_generate_content_without_deprecated_sampling_parameters():
    adapter = get_external_llm_provider_adapter("google")
    request = adapter.build_request(
        model="gemini-3.6-flash",
        system_prompt="system",
        user_content="user",
        max_output_tokens=1024,
        temperature=0.1,
        api_key="google-secret",
    )
    assert request.payload["generationConfig"]["maxOutputTokens"] == 1024
    assert "temperature" not in request.payload["generationConfig"]
    assert request.headers["x-goog-api-key"] == "google-secret"
    normalized = adapter.normalize_response(
        {"candidates": [{"content": {"parts": [{"text": "{\"summary\":\"ok\"}"}]}}]}
    )
    assert normalized["content"][0]["text"] == '{"summary":"ok"}'


def test_xai_adapter_uses_openai_compatible_chat_completions():
    adapter = get_external_llm_provider_adapter("xai")
    request = adapter.build_request(
        model="grok-4.5",
        system_prompt="system",
        user_content="user",
        max_output_tokens=1024,
        temperature=0.1,
        api_key="xai-secret",
    )
    assert request.payload["model"] == "grok-4.5"
    assert request.payload["messages"][0]["role"] == "system"
    assert request.headers["Authorization"] == "Bearer xai-secret"
    normalized = adapter.normalize_response(
        {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}
    )
    assert normalized["content"][0]["text"] == '{"summary":"ok"}'


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        get_external_llm_provider_adapter("unknown")
