"""Opt-in OpenAI fallback for the loopback-first legacy chat facade.

The module owns only the OpenAI Responses API transport. It is intentionally
separate from the local Ollama transport so callers depend on a small chat
provider contract and new providers can be added without changing them.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import os
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_NEVER_ALLOWED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("168.63.129.16"),
    ipaddress.ip_address("100.100.100.200"),
}


class ChatProvider(Protocol):
    """Minimal interface implemented by optional secondary chat providers."""

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str | None: ...


class OpenAIFallbackError(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid integer configuration for %s", name)
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class OpenAIFallbackConfig:
    enabled: bool
    api_key: str
    model: str
    api_url: str
    allowed_hosts: tuple[str, ...]
    timeout_seconds: int
    max_response_bytes: int
    max_output_tokens: int

    @classmethod
    def from_environment(cls) -> "OpenAIFallbackConfig":
        allowed_hosts = tuple(
            host.strip().lower().rstrip(".")
            for host in os.getenv("OPENAI_ALLOWED_HOSTS", "api.openai.com").split(",")
            if host.strip()
        )
        return cls(
            enabled=_env_bool("OPENAI_FALLBACK_ENABLED"),
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
            api_url=os.getenv(
                "OPENAI_API_URL",
                "https://api.openai.com/v1/responses",
            ).strip(),
            allowed_hosts=allowed_hosts,
            timeout_seconds=_env_int(
                "OPENAI_FALLBACK_TIMEOUT_SECONDS",
                45,
                minimum=5,
                maximum=120,
            ),
            max_response_bytes=_env_int(
                "OPENAI_FALLBACK_MAX_RESPONSE_BYTES",
                1_048_576,
                minimum=65_536,
                maximum=4_194_304,
            ),
            max_output_tokens=_env_int(
                "OPENAI_MAX_OUTPUT_TOKENS",
                2_048,
                minimum=128,
                maximum=16_384,
            ),
        )


@dataclass(frozen=True, slots=True)
class _OpenAIEndpoint:
    hostname: str
    port: int
    path: str
    resolved_ips: tuple[str, ...]


def _validate_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address in _NEVER_ALLOWED_IPS:
        raise OpenAIFallbackError("openai_metadata_address_blocked")
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        raise OpenAIFallbackError("openai_non_global_address_blocked")


def _resolve_public_ips(hostname: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise OpenAIFallbackError("openai_dns_resolution_failed") from exc

    addresses: dict[str, ipaddress.IPv4Address | ipaddress.IPv6Address] = {}
    for record in records:
        if len(record) < 5 or not record[4]:
            continue
        raw = str(record[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        _validate_public_address(address)
        addresses[str(address)] = address
    if not addresses:
        raise OpenAIFallbackError("openai_dns_no_addresses")
    return tuple(sorted(addresses))


def _validate_endpoint(config: OpenAIFallbackConfig) -> _OpenAIEndpoint:
    try:
        parsed = urlsplit(config.api_url)
    except ValueError as exc:
        raise OpenAIFallbackError("openai_endpoint_invalid") from exc

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or hostname not in set(config.allowed_hosts)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1/responses"
        or "*" in config.allowed_hosts
    ):
        raise OpenAIFallbackError("openai_endpoint_forbidden")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise OpenAIFallbackError("openai_endpoint_invalid") from exc
    if port != 443:
        raise OpenAIFallbackError("openai_endpoint_port_forbidden")
    return _OpenAIEndpoint(
        hostname=hostname,
        port=port,
        path=parsed.path,
        resolved_ips=_resolve_public_ips(hostname, port),
    )


class _PinnedOpenAIConnection(http.client.HTTPSConnection):
    def __init__(self, endpoint: _OpenAIEndpoint, timeout_seconds: int) -> None:
        self._endpoint = endpoint
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        super().__init__(
            endpoint.hostname,
            endpoint.port,
            timeout=timeout_seconds,
            context=context,
        )

    def connect(self) -> None:
        if self._tunnel_host:
            raise OpenAIFallbackError("openai_proxy_tunnel_forbidden")
        last_error: OSError | None = None
        raw_socket: socket.socket | None = None
        for address in self._endpoint.resolved_ips:
            try:
                raw_socket = socket.create_connection(
                    (address, self._endpoint.port),
                    timeout=float(self.timeout),
                    source_address=self.source_address,
                )
                break
            except OSError as exc:
                last_error = exc
        if raw_socket is None:
            raise OpenAIFallbackError("openai_connect_failed") from last_error
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._endpoint.hostname,
            )
            self.sock.settimeout(float(self.timeout))
        except Exception:
            raw_socket.close()
            raise


def _read_bounded_json(
    response: http.client.HTTPResponse,
    *,
    max_response_bytes: int,
) -> dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        response.close()
        raise OpenAIFallbackError(f"openai_http_{response.status}")

    declared = response.getheader("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            response.close()
            raise OpenAIFallbackError("openai_invalid_content_length") from exc
        if declared_size < 0 or declared_size > max_response_bytes:
            response.close()
            raise OpenAIFallbackError("openai_response_too_large")

    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_response_bytes:
                raise OpenAIFallbackError("openai_response_too_large")
            chunks.append(chunk)
    finally:
        response.close()

    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIFallbackError("openai_invalid_json") from exc
    if not isinstance(payload, dict):
        raise OpenAIFallbackError("openai_invalid_shape")
    return payload


def _extract_output_text(payload: dict[str, Any]) -> str | None:
    text_parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
    result = "\n".join(text_parts).strip()
    return result or None


class DisabledChatProvider:
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str | None:
        _ = (system_prompt, user_prompt, temperature)
        return None


class OpenAIResponsesChatProvider:
    """OpenAI Responses API adapter with strict endpoint and response bounds."""

    def __init__(self, config: OpenAIFallbackConfig) -> None:
        self.config = config

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str | None:
        _ = temperature  # Keep the provider contract stable across model families.
        if not self.config.enabled or not self.config.api_key or not self.config.model:
            return None

        endpoint = _validate_endpoint(self.config)
        request_payload = {
            "model": self.config.model,
            "instructions": system_prompt,
            "input": user_prompt,
            "max_output_tokens": self.config.max_output_tokens,
            "store": False,
        }
        body = json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        connection = _PinnedOpenAIConnection(endpoint, self.config.timeout_seconds)
        try:
            connection.request(
                "POST",
                endpoint.path,
                body=body,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "GuardianAI-OpenAI-Fallback/1",
                },
            )
            response_payload = _read_bounded_json(
                connection.getresponse(),
                max_response_bytes=self.config.max_response_bytes,
            )
        except OpenAIFallbackError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise OpenAIFallbackError("openai_transport_failed") from exc
        finally:
            connection.close()

        return _extract_output_text(response_payload)


def build_openai_fallback_provider() -> ChatProvider:
    config = OpenAIFallbackConfig.from_environment()
    if not config.enabled:
        return DisabledChatProvider()
    return OpenAIResponsesChatProvider(config)
