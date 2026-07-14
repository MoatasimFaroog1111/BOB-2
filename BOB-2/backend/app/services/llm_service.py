"""Local-only compatibility LLM service.

Legacy callers may use this module without a tenant security context, so it is intentionally
incapable of contacting an Internet provider. External LLM requests must go through
``ExternalLLMGateway`` with explicit organization, user, purpose, DPA, and audit context.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import socket
import ssl
from typing import Any, Optional
from urllib.parse import urlsplit

from app.core.config import settings

logger = logging.getLogger(__name__)


class LocalLLMError(RuntimeError):
    pass


def _validated_local_endpoint() -> tuple[str, int, str, tuple[str, ...], str]:
    try:
        parsed = urlsplit(settings.OLLAMA_BASE_URL)
    except ValueError as exc:
        raise LocalLLMError("invalid_local_llm_url") from exc

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if (
        scheme not in {"http", "https"}
        or hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise LocalLLMError("local_llm_must_be_loopback_only")

    try:
        port = parsed.port or (443 if scheme == "https" else 11434)
    except ValueError as exc:
        raise LocalLLMError("invalid_local_llm_port") from exc
    if not 1 <= port <= 65535:
        raise LocalLLMError("invalid_local_llm_port")

    try:
        records = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise LocalLLMError("local_llm_dns_failed") from exc

    addresses: dict[str, ipaddress.IPv4Address | ipaddress.IPv6Address] = {}
    for record in records:
        if len(record) < 5 or not record[4]:
            continue
        raw = str(record[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_loopback:
            raise LocalLLMError("local_llm_resolved_outside_loopback")
        addresses[str(address)] = address
    if not addresses:
        raise LocalLLMError("local_llm_no_loopback_address")
    return hostname, port, "/api/chat", tuple(sorted(addresses)), scheme


class _PinnedLocalConnection(http.client.HTTPConnection):
    def __init__(
        self,
        *,
        hostname: str,
        port: int,
        addresses: tuple[str, ...],
        scheme: str,
    ) -> None:
        self._addresses = addresses
        self._scheme = scheme
        self._ssl_context = ssl.create_default_context() if scheme == "https" else None
        super().__init__(hostname, port, timeout=settings.LOCAL_LLM_TIMEOUT_SECONDS)

    def connect(self) -> None:
        if self._tunnel_host:
            raise LocalLLMError("local_llm_proxy_tunnel_forbidden")
        last_error: OSError | None = None
        raw_socket: socket.socket | None = None
        for address in self._addresses:
            try:
                raw_socket = socket.create_connection(
                    (address, self.port),
                    timeout=float(settings.LOCAL_LLM_TIMEOUT_SECONDS),
                    source_address=self.source_address,
                )
                break
            except OSError as exc:
                last_error = exc
        if raw_socket is None:
            raise LocalLLMError("local_llm_connect_failed") from last_error
        if self._scheme == "https":
            try:
                self.sock = self._ssl_context.wrap_socket(raw_socket, server_hostname=self.host)
            except Exception:
                raw_socket.close()
                raise
        else:
            self.sock = raw_socket
        self.sock.settimeout(float(settings.LOCAL_LLM_TIMEOUT_SECONDS))


def _read_bounded_json(response: http.client.HTTPResponse) -> dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        response.close()
        raise LocalLLMError("local_llm_http_error")
    declared = response.getheader("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            response.close()
            raise LocalLLMError("local_llm_invalid_content_length") from exc
        if declared_size < 0 or declared_size > settings.LOCAL_LLM_MAX_RESPONSE_BYTES:
            response.close()
            raise LocalLLMError("local_llm_response_too_large")

    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.LOCAL_LLM_MAX_RESPONSE_BYTES:
                raise LocalLLMError("local_llm_response_too_large")
            chunks.append(chunk)
    finally:
        response.close()
    try:
        result = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalLLMError("local_llm_invalid_json") from exc
    if not isinstance(result, dict):
        raise LocalLLMError("local_llm_invalid_shape")
    return result


def _call_local_ollama(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> Optional[str]:
    hostname, port, path, addresses, scheme = _validated_local_endpoint()
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    connection = _PinnedLocalConnection(
        hostname=hostname,
        port=port,
        addresses=addresses,
        scheme=scheme,
    )
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "GuardianAI-Local-LLM/1",
            },
        )
        result = _read_bounded_json(connection.getresponse())
        content = result.get("message", {}).get("content", "")
        return content.strip() if isinstance(content, str) and content.strip() else None
    finally:
        connection.close()


def chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    timeout: int = 120,
) -> Optional[str]:
    """Use a configured loopback-only Ollama instance, or return ``None``.

    ``timeout`` remains in the signature for compatibility, but the bounded configuration
    value is authoritative. There is deliberately no external-provider fallback.
    """

    _ = timeout
    if not settings.LOCAL_LLM_ENABLED:
        return None
    try:
        result = _call_local_ollama(system_prompt, user_prompt, temperature)
    except Exception:
        logger.info("Local LLM unavailable; continuing without model assistance")
        return None
    if result:
        logger.info("LLM response received from the configured local model")
    return result
