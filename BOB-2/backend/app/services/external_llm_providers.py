"""Provider-specific external LLM adapters and immutable catalog metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ExternalLLMAdapter(Protocol):
    def endpoint(self, model: str) -> str: ...

    def build_request(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        temperature: float,
    ) -> dict[str, Any]: ...

    def headers(self, api_key: str) -> dict[str, str]: ...

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _normalized_text(text: str) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("The external LLM response did not contain text.")
    return {"content": [{"type": "text", "text": text}]}


class AnthropicMessagesAdapter:
    def endpoint(self, model: str) -> str:
        _ = model
        return "https://api.anthropic.com/v1/messages"

    def build_request(self, *, model: str, system_prompt: str, user_content: str, temperature: float) -> dict[str, Any]:
        return {
            "model": model,
            "max_tokens": 2048,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        }

    def headers(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        content = payload.get("content")
        if isinstance(content, list) and content:
            text = content[0].get("text") if isinstance(content[0], dict) else None
            if isinstance(text, str):
                return _normalized_text(text)
        raise ValueError("Anthropic returned an invalid response shape.")


class OpenAIResponsesAdapter:
    def endpoint(self, model: str) -> str:
        _ = model
        return "https://api.openai.com/v1/responses"

    def build_request(self, *, model: str, system_prompt: str, user_content: str, temperature: float) -> dict[str, Any]:
        _ = temperature
        return {
            "model": model,
            "max_output_tokens": 2048,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

    def headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        direct = payload.get("output_text")
        if isinstance(direct, str):
            return _normalized_text(direct)
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    return _normalized_text(content["text"])
        raise ValueError("OpenAI returned an invalid response shape.")


class OpenAIChatAdapter:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def endpoint(self, model: str) -> str:
        _ = model
        return self._base_url

    def build_request(self, *, model: str, system_prompt: str, user_content: str, temperature: float) -> dict[str, Any]:
        return {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

    def headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            text = message.get("content") if isinstance(message, dict) else None
            if isinstance(text, str):
                return _normalized_text(text)
        raise ValueError("The provider returned an invalid chat-completion response.")


class GeminiGenerateContentAdapter:
    def endpoint(self, model: str) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def build_request(self, *, model: str, system_prompt: str, user_content: str, temperature: float) -> dict[str, Any]:
        _ = model
        return {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048},
        }

    def headers(self, api_key: str) -> dict[str, str]:
        return {"x-goog-api-key": api_key}

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            first_part = parts[0] if isinstance(parts, list) and parts else None
            if isinstance(first_part, dict) and isinstance(first_part.get("text"), str):
                return _normalized_text(first_part["text"])
        raise ValueError("Gemini returned an invalid response shape.")


@dataclass(frozen=True, slots=True)
class ExternalLLMProviderDefinition:
    key: str
    display_name: str
    models: tuple[str, ...]
    adapter: ExternalLLMAdapter

    def public_dict(self, allowed_pairs: set[str]) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "models": [
                {"id": model, "enabled": f"{self.key}:{model}".lower() in allowed_pairs}
                for model in self.models
            ],
        }


class ExternalLLMProviderRegistry:
    def __init__(self, definitions: tuple[ExternalLLMProviderDefinition, ...]) -> None:
        self._definitions = {definition.key: definition for definition in definitions}

    def get(self, provider: str) -> ExternalLLMProviderDefinition:
        definition = self._definitions.get(provider.strip().lower())
        if definition is None:
            raise ValueError(f"Unsupported external LLM provider: {provider}")
        return definition

    def catalog(self, allowed_pairs: set[str]) -> list[dict[str, Any]]:
        return [definition.public_dict(allowed_pairs) for definition in self._definitions.values()]


external_llm_provider_registry = ExternalLLMProviderRegistry((
    ExternalLLMProviderDefinition("openai", "OpenAI", ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.4"), OpenAIResponsesAdapter()),
    ExternalLLMProviderDefinition("anthropic", "Anthropic", ("claude-sonnet-5", "claude-opus-5", "claude-sonnet-4-6"), AnthropicMessagesAdapter()),
    ExternalLLMProviderDefinition("google", "Google Gemini", ("gemini-3.6-flash", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite"), GeminiGenerateContentAdapter()),
    ExternalLLMProviderDefinition("xai", "xAI", ("grok-4.5", "grok-4.3"), OpenAIChatAdapter("https://api.x.ai/v1/chat/completions")),
))
