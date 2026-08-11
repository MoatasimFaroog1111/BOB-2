"""Multi-provider extension of the tenant-aware external LLM gateway.

Authorization, disclosure policy, redaction, auditing and the bounded network
boundary remain centralized in ``external_llm_gateway``.  This class delegates
only provider wire-format differences to small adapters.
"""

from __future__ import annotations

import http.client
import json
import ssl
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings
from app.services.external_llm_gateway import (
    ExternalLLMGateway,
    ExternalLLMPolicyDenied,
    ExternalLLMProviderError,
    _ExternalEndpoint,
    _PinnedHTTPSConnection,
    _bounded_response_json,
    _csv_items,
    _resolve_validated_ips,
    record_external_llm_event,
    sanitize_external_payload,
)
from app.services.external_llm_provider_adapters import (
    ExternalLLMProviderAdapter,
    get_external_llm_provider_adapter,
)


class MultiProviderExternalLLMGateway(ExternalLLMGateway):
    """External LLM gateway supporting approved OpenAI, Anthropic, Google and xAI APIs."""

    def __init__(
        self,
        *,
        db,
        context,
        provider: str,
        model: str,
        api_key: str | None = None,
        api_url: str | None = None,
        transport=None,
    ) -> None:
        normalized_provider = provider.strip().lower()
        try:
            self.adapter: ExternalLLMProviderAdapter = get_external_llm_provider_adapter(
                normalized_provider
            )
        except ValueError as exc:
            raise ExternalLLMProviderError("external_llm_provider_unsupported") from exc
        resolved_url = api_url or self.adapter.default_url(model.strip())
        super().__init__(
            db=db,
            context=context,
            provider=normalized_provider,
            model=model,
            api_key=api_key,
            api_url=resolved_url,
            transport=transport,
        )

    def execute_chat_completion(
        self,
        *,
        system_prompt: str,
        structured_payload: dict[str, Any],
        raw_document_text: str = "",
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self.authorize()
        sanitized = sanitize_external_payload(
            structured_payload=structured_payload,
            raw_document_text=raw_document_text,
            policy=policy,
        )
        # JSON output is enforced by the accounting system prompt.  Provider
        # response-format extensions differ, so they are intentionally not
        # forwarded across vendors.
        _ = response_format
        user_content = json.dumps(sanitized.payload, ensure_ascii=False)
        try:
            provider_request = self.adapter.build_request(
                model=self.model,
                system_prompt=system_prompt,
                user_content=user_content,
                max_output_tokens=1024,
                temperature=temperature,
                api_key=self.api_key,
            )
        except Exception as exc:
            raise ExternalLLMProviderError("external_llm_request_build_failed") from exc

        request_bytes = json.dumps(
            provider_request.payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(request_bytes) > settings.EXTERNAL_LLM_MAX_REQUEST_BYTES:
            self._deny("external_llm_request_too_large", policy=policy)

        record_external_llm_event(
            self.db,
            context=self.context,
            action="external_llm_disclosure_started",
            details={
                "provider": self.provider,
                "model": self.model,
                "policy_id": policy.id,
                "policy_version": policy.policy_version,
                "dpa_version": policy.dpa_version,
                "payload_hash": sanitized.payload_hash,
                "sanitized_payload_bytes": sanitized.input_bytes,
                "provider_request_bytes": len(request_bytes),
                "included_redacted_text_chars": sanitized.included_redacted_text_chars,
                "allow_financial_values": policy.allow_financial_values,
                "redaction_counts": sanitized.redaction_counts,
            },
        )
        try:
            raw_response = self.transport(
                self.api_url,
                provider_request.payload,
                self.api_key,
            )
            normalized_response = self.adapter.normalize_response(raw_response)
        except Exception as exc:
            reason = getattr(exc, "reason", "external_llm_provider_failed")
            record_external_llm_event(
                self.db,
                context=self.context,
                action="external_llm_disclosure_failed",
                details={
                    "provider": self.provider,
                    "model": self.model,
                    "policy_id": policy.id,
                    "policy_version": policy.policy_version,
                    "payload_hash": sanitized.payload_hash,
                    "reason": reason,
                },
            )
            if isinstance(exc, ExternalLLMProviderError):
                raise
            if isinstance(exc, ExternalLLMPolicyDenied):
                raise
            raise ExternalLLMProviderError("external_llm_provider_failed") from exc

        record_external_llm_event(
            self.db,
            context=self.context,
            action="external_llm_disclosure_succeeded",
            details={
                "provider": self.provider,
                "model": self.model,
                "policy_id": policy.id,
                "policy_version": policy.policy_version,
                "payload_hash": sanitized.payload_hash,
                "output_chars": len(
                    json.dumps(normalized_response, ensure_ascii=False)
                ),
            },
        )
        return normalized_response

    def _validate_provider_endpoint(self, raw_url: str) -> _ExternalEndpoint:
        try:
            parsed = urlsplit(raw_url)
        except ValueError as exc:
            raise ExternalLLMProviderError("external_llm_endpoint_invalid") from exc
        hostname = (parsed.hostname or "").rstrip(".").lower()
        allowed_hosts = set(_csv_items(settings.EXTERNAL_LLM_ALLOWED_HOSTS))
        if (
            parsed.scheme.lower() != "https"
            or not hostname
            or hostname not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ExternalLLMProviderError("external_llm_endpoint_forbidden")
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise ExternalLLMProviderError("external_llm_endpoint_invalid") from exc
        if port != 443:
            raise ExternalLLMProviderError("external_llm_endpoint_port_forbidden")
        path = parsed.path or "/"
        if (
            ".." in path
            or "\\" in path
            or "%" in path
            or "//" in path
            or not self.adapter.path_is_allowed(path, self.model)
        ):
            raise ExternalLLMProviderError("external_llm_endpoint_path_forbidden")
        return _ExternalEndpoint(
            hostname=hostname,
            port=port,
            path=path,
            resolved_ips=_resolve_validated_ips(hostname, port),
        )

    def _post_json(
        self,
        api_url: str,
        payload: dict[str, Any],
        api_key: str,
    ) -> dict[str, Any]:
        endpoint = self._validate_provider_endpoint(api_url)
        provider_request = self.adapter.build_request(
            model=self.model,
            system_prompt="",
            user_content="",
            max_output_tokens=1024,
            temperature=0.1,
            api_key=api_key,
        )
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > settings.EXTERNAL_LLM_MAX_REQUEST_BYTES:
            raise ExternalLLMProviderError("external_llm_request_too_large")
        connection = _PinnedHTTPSConnection(endpoint)
        try:
            connection.request(
                "POST",
                endpoint.path,
                body=body,
                headers=provider_request.headers,
            )
            return _bounded_response_json(connection.getresponse())
        except ExternalLLMProviderError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ExternalLLMProviderError("external_llm_transport_failed") from exc
        finally:
            connection.close()
