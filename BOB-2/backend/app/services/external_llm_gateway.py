"""Tenant-aware, fail-closed gateway for external LLM disclosures.

No caller may treat an API key as organizational consent. Every request needs an active
organization policy, a current system user, an approved purpose/provider/model, a current
DPA acknowledgement, deterministic redaction, and an audit event committed before bytes
leave the application.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import AuditLog, Organization, User
from app.models.external_llm import ExternalLLMPolicy

ALLOWED_EXTERNAL_LLM_PURPOSES = frozenset(
    {
        "accounting_reasoning",
        "natural_language_intent",
        "bank_reconciliation_matching",
    }
)
ALLOWED_RETENTION_MODES = frozenset(
    {
        "contractual_zero_retention",
        "contractual_no_training",
    }
)

_NEVER_ALLOWED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("168.63.129.16"),
    ipaddress.ip_address("100.100.100.200"),
}

_SENSITIVE_KEY_MARKERS = (
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "private_key",
)
_PARTY_KEY_MARKERS = (
    "party",
    "partner",
    "supplier",
    "vendor",
    "customer",
    "employee",
    "person",
    "full_name",
    "contact_name",
    "address",
)
_IDENTIFIER_KEY_MARKERS = (
    "iban",
    "account_number",
    "bank_account",
    "vat_number",
    "tax_number",
    "national_id",
    "identity",
    "email",
    "phone",
    "mobile",
    "reference",
    "invoice_number",
)
_FINANCIAL_KEY_MARKERS = (
    "amount",
    "subtotal",
    "total",
    "balance",
    "debit",
    "credit",
    "price",
    "cost",
    "salary",
    "wage",
    "financial_value",
)

_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email",
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ),
    (
        "iban",
        re.compile(r"(?i)\b[A-Z]{2}\d{2}(?:[\s-]?[A-Z0-9]){11,30}\b"),
    ),
    (
        "saudi_vat_number",
        re.compile(r"(?<!\d)3\d{14}(?!\d)"),
    ),
    (
        "saudi_identity",
        re.compile(r"(?<!\d)[12]\d{9}(?!\d)"),
    ),
    (
        "phone",
        re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)"),
    ),
    (
        "long_identifier",
        re.compile(r"(?<!\d)\d(?:[\s-]?\d){11,23}(?!\d)"),
    ),
)


class ExternalLLMPolicyDenied(RuntimeError):
    def __init__(
        self,
        reason: str,
        public_message: str = "External AI processing is not authorized for this organization.",
    ) -> None:
        super().__init__(public_message)
        self.reason = reason
        self.public_message = public_message


class ExternalLLMProviderError(RuntimeError):
    def __init__(self, reason: str, public_message: str = "The external AI provider request failed.") -> None:
        super().__init__(public_message)
        self.reason = reason
        self.public_message = public_message


class ExternalLLMAuditError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalLLMRequestContext:
    organization_id: int
    user_id: int
    purpose: str
    source_type: str
    request_id: str


@dataclass(frozen=True, slots=True)
class SanitizedExternalPayload:
    payload: dict[str, Any]
    payload_hash: str
    input_bytes: int
    redaction_counts: dict[str, int]
    included_redacted_text_chars: int


def _csv_items(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in details.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS):
            safe[key] = "[REDACTED]"
        elif isinstance(value, str) and len(value) > 500:
            safe[key] = value[:500]
        else:
            safe[key] = value
    return safe


def record_external_llm_event(
    db: Session,
    *,
    context: ExternalLLMRequestContext,
    action: str,
    details: dict[str, Any],
) -> AuditLog:
    event = AuditLog(
        organization_id=context.organization_id,
        user_id=context.user_id,
        action=action,
        entity_type="external_llm",
        entity_id=context.request_id,
        details=_safe_details(
            {
                "request_id": context.request_id,
                "purpose": context.purpose,
                "source_type": context.source_type,
                **details,
            }
        ),
    )
    try:
        db.add(event)
        db.commit()
        db.refresh(event)
    except Exception as exc:
        db.rollback()
        raise ExternalLLMAuditError("Failed to persist the external LLM audit event.") from exc
    return event


def _redact_text(value: str, counts: dict[str, int]) -> str:
    redacted = value
    for label, pattern in _TEXT_PATTERNS:
        redacted, substitutions = pattern.subn(f"[REDACTED:{label}]", redacted)
        if substitutions:
            counts[label] = counts.get(label, 0) + substitutions
    return redacted


def _redact_structure(
    value: Any,
    *,
    allow_financial_values: bool,
    counts: dict[str, int],
    key_hint: str = "",
) -> Any:
    lowered_key = key_hint.lower()
    if any(marker in lowered_key for marker in _SENSITIVE_KEY_MARKERS):
        counts["secret_field"] = counts.get("secret_field", 0) + 1
        return "[REDACTED:secret]"
    if any(marker in lowered_key for marker in _PARTY_KEY_MARKERS):
        counts["party_field"] = counts.get("party_field", 0) + 1
        return "[REDACTED:party]"
    if any(marker in lowered_key for marker in _IDENTIFIER_KEY_MARKERS):
        counts["identifier_field"] = counts.get("identifier_field", 0) + 1
        return "[REDACTED:identifier]"
    if any(marker in lowered_key for marker in _FINANCIAL_KEY_MARKERS) and not allow_financial_values:
        counts["financial_value"] = counts.get("financial_value", 0) + 1
        return "[REDACTED:financial_value]"

    if isinstance(value, dict):
        return {
            str(key): _redact_structure(
                child,
                allow_financial_values=allow_financial_values,
                counts=counts,
                key_hint=str(key),
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_structure(
                child,
                allow_financial_values=allow_financial_values,
                counts=counts,
                key_hint=key_hint,
            )
            for child in value
        ]
    if isinstance(value, tuple):
        return [
            _redact_structure(
                child,
                allow_financial_values=allow_financial_values,
                counts=counts,
                key_hint=key_hint,
            )
            for child in value
        ]
    if isinstance(value, str):
        return _redact_text(value, counts)
    if isinstance(value, (int, float)) and not allow_financial_values and any(
        marker in lowered_key for marker in _FINANCIAL_KEY_MARKERS
    ):
        counts["financial_value"] = counts.get("financial_value", 0) + 1
        return "[REDACTED:financial_value]"
    return value


def sanitize_external_payload(
    *,
    structured_payload: dict[str, Any],
    raw_document_text: str,
    policy: ExternalLLMPolicy,
) -> SanitizedExternalPayload:
    counts: dict[str, int] = {}
    sanitized = _redact_structure(
        structured_payload,
        allow_financial_values=policy.allow_financial_values,
        counts=counts,
    )
    included_chars = 0
    if policy.allow_redacted_document_text and policy.max_redacted_text_chars > 0:
        global_limit = max(0, int(settings.EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS))
        effective_limit = min(policy.max_redacted_text_chars, global_limit)
        redacted_text = _redact_text((raw_document_text or "")[:effective_limit], counts)
        included_chars = len(redacted_text)
        sanitized["redacted_document_text"] = redacted_text
    else:
        counts["raw_document_text_omitted"] = counts.get("raw_document_text_omitted", 0) + 1

    encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > settings.EXTERNAL_LLM_MAX_REQUEST_BYTES:
        raise ExternalLLMPolicyDenied("external_llm_sanitized_payload_too_large")
    return SanitizedExternalPayload(
        payload=sanitized,
        payload_hash=hashlib.sha256(encoded).hexdigest(),
        input_bytes=len(encoded),
        redaction_counts=counts,
        included_redacted_text_chars=included_chars,
    )


def _validate_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address in _NEVER_ALLOWED_IPS:
        raise ExternalLLMProviderError("external_llm_metadata_address_blocked")
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        raise ExternalLLMProviderError("external_llm_non_global_address_blocked")


def _resolve_validated_ips(hostname: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise ExternalLLMProviderError("external_llm_dns_resolution_failed") from exc
    addresses: dict[str, ipaddress.IPv4Address | ipaddress.IPv6Address] = {}
    for record in records:
        if len(record) < 5 or not record[4]:
            continue
        raw = str(record[4][0]).split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(raw)
        except ValueError:
            continue
        _validate_address(parsed)
        addresses[str(parsed)] = parsed
    if not addresses:
        raise ExternalLLMProviderError("external_llm_dns_no_addresses")
    return tuple(sorted(addresses))


@dataclass(frozen=True, slots=True)
class _ExternalEndpoint:
    hostname: str
    port: int
    path: str
    resolved_ips: tuple[str, ...]


def _validate_external_endpoint(raw_url: str) -> _ExternalEndpoint:
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
    if not path.endswith("/chat/completions") or ".." in path or "\\" in path:
        raise ExternalLLMProviderError("external_llm_endpoint_path_forbidden")
    return _ExternalEndpoint(
        hostname=hostname,
        port=port,
        path=path,
        resolved_ips=_resolve_validated_ips(hostname, port),
    )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, endpoint: _ExternalEndpoint) -> None:
        self._endpoint = endpoint
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        super().__init__(
            host=endpoint.hostname,
            port=endpoint.port,
            timeout=settings.ACCOUNTING_LLM_TIMEOUT_SECONDS,
            context=context,
        )

    def connect(self) -> None:
        if self._tunnel_host:
            raise ExternalLLMProviderError("external_llm_proxy_tunnel_forbidden")
        last_error: OSError | None = None
        raw_socket: socket.socket | None = None
        for address in self._endpoint.resolved_ips:
            try:
                raw_socket = socket.create_connection(
                    (address, self._endpoint.port),
                    timeout=float(settings.ACCOUNTING_LLM_TIMEOUT_SECONDS),
                    source_address=self.source_address,
                )
                break
            except OSError as exc:
                last_error = exc
        if raw_socket is None:
            raise ExternalLLMProviderError("external_llm_connect_failed") from last_error
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._endpoint.hostname,
            )
            self.sock.settimeout(float(settings.ACCOUNTING_LLM_TIMEOUT_SECONDS))
        except Exception:
            raw_socket.close()
            raise


def _bounded_response_json(response: http.client.HTTPResponse) -> dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        response.close()
        raise ExternalLLMProviderError(f"external_llm_http_{response.status}")
    declared = response.getheader("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            response.close()
            raise ExternalLLMProviderError("external_llm_response_length_invalid") from exc
        if declared_size < 0 or declared_size > settings.EXTERNAL_LLM_MAX_RESPONSE_BYTES:
            response.close()
            raise ExternalLLMProviderError("external_llm_response_too_large")
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.EXTERNAL_LLM_MAX_RESPONSE_BYTES:
                raise ExternalLLMProviderError("external_llm_response_too_large")
            chunks.append(chunk)
    finally:
        response.close()
    try:
        parsed = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalLLMProviderError("external_llm_response_invalid_json") from exc
    if not isinstance(parsed, dict):
        raise ExternalLLMProviderError("external_llm_response_invalid_shape")
    return parsed


Transport = Callable[[str, dict[str, Any], str], dict[str, Any]]


class ExternalLLMGateway:
    def __init__(
        self,
        *,
        db: Session,
        context: ExternalLLMRequestContext,
        provider: str,
        model: str,
        api_key: str | None = None,
        api_url: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.db = db
        self.context = context
        self.provider = provider.strip().lower()
        self.model = model.strip()
        self.api_key = api_key if api_key is not None else self._resolve_api_key()
        self.api_url = api_url or settings.ACCOUNTING_LLM_API_URL
        self.transport = transport or self._post_json

    def _resolve_api_key(self) -> str:
        if self.provider == "deepseek":
            return settings.ACCOUNTING_LLM_API_KEY or settings.DEEPSEEK_API_KEY
        return settings.ACCOUNTING_LLM_API_KEY

    def _deny(self, reason: str, *, policy: ExternalLLMPolicy | None = None) -> None:
        try:
            record_external_llm_event(
                self.db,
                context=self.context,
                action="external_llm_disclosure_blocked",
                details={
                    "reason": reason,
                    "provider": self.provider,
                    "model": self.model,
                    "policy_id": policy.id if policy else None,
                    "policy_version": policy.policy_version if policy else None,
                },
            )
        except ExternalLLMAuditError:
            raise
        raise ExternalLLMPolicyDenied(reason)

    def authorize(self) -> ExternalLLMPolicy:
        organization = self.db.query(Organization).filter(Organization.id == self.context.organization_id).first()
        user = self.db.query(User).filter(User.id == self.context.user_id).first()
        policy = (
            self.db.query(ExternalLLMPolicy)
            .filter(ExternalLLMPolicy.organization_id == self.context.organization_id)
            .first()
        )
        if organization is None or not organization.is_active:
            self._deny("external_llm_organization_inactive", policy=policy)
        if user is None or not user.is_active or user.organization_id != self.context.organization_id:
            self._deny("external_llm_user_invalid", policy=policy)
        if not settings.EXTERNAL_LLM_ENABLED:
            self._deny("external_llm_global_kill_switch", policy=policy)
        if policy is None or not policy.external_llm_enabled:
            self._deny("external_llm_tenant_not_enabled", policy=policy)
        if self.context.purpose not in ALLOWED_EXTERNAL_LLM_PURPOSES:
            self._deny("external_llm_purpose_unknown", policy=policy)
        if self.context.purpose not in set(policy.allowed_purposes or []):
            self._deny("external_llm_purpose_not_approved", policy=policy)
        if self.provider != (policy.approved_provider or "").strip().lower():
            self._deny("external_llm_provider_not_approved", policy=policy)
        if self.model != (policy.approved_model or "").strip():
            self._deny("external_llm_model_not_approved", policy=policy)
        if self.provider not in set(_csv_items(settings.EXTERNAL_LLM_ALLOWED_PROVIDERS)):
            self._deny("external_llm_provider_not_globally_allowed", policy=policy)
        pair = f"{self.provider}:{self.model}".lower()
        if pair not in set(_csv_items(settings.EXTERNAL_LLM_ALLOWED_MODELS)):
            self._deny("external_llm_model_not_globally_allowed", policy=policy)
        if (
            not policy.dpa_version
            or policy.dpa_version != settings.EXTERNAL_LLM_REQUIRED_DPA_VERSION
            or not policy.dpa_reference
            or not policy.data_residency_region
            or policy.provider_retention_mode not in ALLOWED_RETENTION_MODES
            or policy.accepted_by_user_id is None
            or policy.accepted_at is None
            or policy.revoked_at is not None
        ):
            self._deny("external_llm_dpa_not_current", policy=policy)
        if policy.max_redacted_text_chars > settings.EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS:
            self._deny("external_llm_text_limit_exceeds_global", policy=policy)
        if not self.api_key:
            self._deny("external_llm_api_key_missing", policy=policy)
        return policy

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
        request_payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(sanitized.payload, ensure_ascii=False),
                },
            ],
        }
        if response_format:
            request_payload["response_format"] = response_format
        request_bytes = json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
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
            response_payload = self.transport(self.api_url, request_payload, self.api_key)
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
            raise ExternalLLMProviderError("external_llm_provider_failed") from exc

        output_chars = len(json.dumps(response_payload, ensure_ascii=False))
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
                "output_chars": output_chars,
            },
        )
        return response_payload

    @staticmethod
    def _post_json(api_url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        endpoint = _validate_external_endpoint(api_url)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > settings.EXTERNAL_LLM_MAX_REQUEST_BYTES:
            raise ExternalLLMProviderError("external_llm_request_too_large")
        connection = _PinnedHTTPSConnection(endpoint)
        try:
            connection.request(
                "POST",
                endpoint.path,
                body=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "GuardianAI-External-LLM-Gateway/1",
                },
            )
            return _bounded_response_json(connection.getresponse())
        except ExternalLLMProviderError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ExternalLLMProviderError("external_llm_transport_failed") from exc
        finally:
            connection.close()


def current_policy_effective_enabled(policy: ExternalLLMPolicy | None) -> bool:
    if policy is None:
        return False
    return bool(
        settings.EXTERNAL_LLM_ENABLED
        and policy.external_llm_enabled
        and policy.dpa_version == settings.EXTERNAL_LLM_REQUIRED_DPA_VERSION
        and policy.dpa_reference
        and policy.data_residency_region
        and policy.provider_retention_mode in ALLOWED_RETENTION_MODES
        and policy.accepted_at
        and policy.accepted_by_user_id
        and policy.revoked_at is None
    )


def utcnow() -> datetime:
    return datetime.utcnow()
