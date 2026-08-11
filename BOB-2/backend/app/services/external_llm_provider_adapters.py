"""Provider-specific request/response adapters for the external LLM boundary.

The security gateway owns authorization, redaction, auditing, SSRF protection and
bounded I/O.  Adapters own only the wire format for one provider.  This keeps the
gateway open for extension without coupling accounting workflows to vendor SDKs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    payload: dict[str, Any]
    headers: dict[str, str]


class ExternalLLMProviderAdapter(Protocol):
    provider_name: str

    def default_url(self, model: str) -> str: ...

    def path_is_allowed(self, path: str, model: str) -> bool: ...

    def build_request(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        max_output_tokens: int,
        temperature: float,
        api_key: str,
    ) -> ProviderRequest: ...

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _normalized_text_response(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("external_llm_provider_text_missing")
    return {"content": [{"type": "text", "text": text}]}


class AnthropicAdapter:
    provider_name = "anthropic"

    def default_url(self, model: str) -> str:
        _ = model
        return "https://api.anthropic.com/v1/messages"

    def path_is_allowed(self, path: str, model: str) -> bool:
        _ = model
        return path == "/v1/messages"

    def build_request(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        max_output_tokens: int,
        temperature: float,
        api_key: str,
    ) -> ProviderRequest:
        # Claude 5 uses adaptive thinking by default and rejects non-default
        # sampling parameters.  Omitting temperature also remains valid for 4.6.
        _ = temperature
        return ProviderRequest(
            payload={
                "model": model,
                "max_tokens": max_output_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
            },
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "GuardianAI-External-LLM-Gateway/2",
            },
        )

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        content = payload.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    return _normalized_text_response(item["text"])
        raise ValueError("external_llm_anthropic_response_invalid")


class OpenAIAdapter:
    provider_name = "openai"

    def default_url(self, model: str) -> str:
        _ = model
        return "https://api.openai.com/v1/responses"

    def path_is_allowed(self, path: str, model: str) -> bool:
        _ = model
        return path == "/v1/responses"

    def build_request(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        max_output_tokens: int,
        temperature: float,
        api_key: str,
    ) -> ProviderRequest:
        # Reasoning-capable GPT-5.x models should not be forced onto legacy
        # sampling controls; the system prompt already constrains JSON output.
        _ = temperature
        return ProviderRequest(
            payload={
                "model": model,
                "instructions": system_prompt,
                "input": user_content,
                "max_output_tokens": max_output_tokens,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "GuardianAI-External-LLM-Gateway/2",
            },
        )

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return _normalized_text_response(output_text)

        output = payload.get("output")
        if isinstance(output, list):
            text_parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        text_parts.append(text)
            if text_parts:
                return _normalized_text_response("".join(text_parts))
        raise ValueError("external_llm_openai_response_invalid")


class GoogleGeminiAdapter:
    provider_name = "google"

    def default_url(self, model: str) -> str:
        safe_model = quote(model, safe="-._")
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{safe_model}:generateContent"
        )

    def path_is_allowed(self, path: str, model: str) -> bool:
        safe_model = quote(model, safe="-._")
        return path == f"/v1beta/models/{safe_model}:generateContent"

    def build_request(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        max_output_tokens: int,
        temperature: float,
        api_key: str,
    ) -> ProviderRequest:
        _ = (model, temperature)
        return ProviderRequest(
            payload={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [
                    {"role": "user", "parts": [{"text": user_content}]}
                ],
                "generationConfig": {
                    "maxOutputTokens": max_output_tokens,
                    "responseMimeType": "application/json",
                },
            },
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "GuardianAI-External-LLM-Gateway/2",
            },
        )

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0]
            if isinstance(candidate, dict):
                content = candidate.get("content")
                if isinstance(content, dict):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        texts = [
                            part.get("text")
                            for part in parts
                            if isinstance(part, dict)
                            and isinstance(part.get("text"), str)
                        ]
                        if texts:
                            return _normalized_text_response("".join(texts))
        raise ValueError("external_llm_google_response_invalid")


class XAIAdapter:
    provider_name = "xai"

    def default_url(self, model: str) -> str:
        _ = model
        return "https://api.x.ai/v1/chat/completions"

    def path_is_allowed(self, path: str, model: str) -> bool:
        _ = model
        return path == "/v1/chat/completions"

    def build_request(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        max_output_tokens: int,
        temperature: float,
        api_key: str,
    ) -> ProviderRequest:
        _ = temperature
        return ProviderRequest(
            payload={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": max_output_tokens,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "GuardianAI-External-LLM-Gateway/2",
            },
        )

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return _normalized_text_response(content)
        raise ValueError("external_llm_xai_response_invalid")


_PROVIDER_ADAPTERS: dict[str, ExternalLLMProviderAdapter] = {
    "anthropic": AnthropicAdapter(),
    "openai": OpenAIAdapter(),
    "google": GoogleGeminiAdapter(),
    "xai": XAIAdapter(),
}


def get_external_llm_provider_adapter(provider: str) -> ExternalLLMProviderAdapter:
    key = provider.strip().lower()
    adapter = _PROVIDER_ADAPTERS.get(key)
    if adapter is None:
        raise ValueError(f"Unsupported external LLM provider: {provider}")
    return adapter


def supported_external_llm_providers() -> tuple[str, ...]:
    return tuple(_PROVIDER_ADAPTERS)
