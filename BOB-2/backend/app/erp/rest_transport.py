"""DNS-pinned, bounded REST transport for non-Odoo ERP providers."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
from typing import Any

from app.core.config import settings
from app.security.outbound_network import OutboundPolicyError, ValidatedOutboundTarget, validate_erp_base_url


def _connect_validated_socket(target: ValidatedOutboundTarget) -> socket.socket:
    last_error: OSError | None = None
    for address in target.resolved_ips:
        try:
            sock = socket.create_connection(
                (address, target.port),
                timeout=float(settings.ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS),
            )
            sock.settimeout(float(settings.ERP_OUTBOUND_READ_TIMEOUT_SECONDS))
            return sock
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OutboundPolicyError("erp_no_validated_address")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, target: ValidatedOutboundTarget) -> None:
        self._target = target
        super().__init__(
            host=target.hostname,
            port=target.port,
            timeout=settings.ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS,
        )

    def connect(self) -> None:
        if self._tunnel_host:
            raise OutboundPolicyError("erp_proxy_tunnel_forbidden")
        self.sock = _connect_validated_socket(self._target)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, target: ValidatedOutboundTarget) -> None:
        self._target = target
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        super().__init__(
            host=target.hostname,
            port=target.port,
            timeout=settings.ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS,
            context=context,
        )

    def connect(self) -> None:
        if self._tunnel_host:
            raise OutboundPolicyError("erp_proxy_tunnel_forbidden")
        raw_socket = _connect_validated_socket(self._target)
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._target.hostname,
            )
            self.sock.settimeout(float(settings.ERP_OUTBOUND_READ_TIMEOUT_SECONDS))
        except Exception:
            raw_socket.close()
            raise


def _read_bounded(response: http.client.HTTPResponse) -> bytes:
    declared = response.getheader("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            response.close()
            raise OutboundPolicyError("erp_response_length_invalid") from exc
        if declared_size < 0 or declared_size > settings.ERP_OUTBOUND_MAX_RESPONSE_BYTES:
            response.close()
            raise OutboundPolicyError("erp_response_too_large")

    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.ERP_OUTBOUND_MAX_RESPONSE_BYTES:
                raise OutboundPolicyError("erp_response_too_large")
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


def request_json(
    *,
    base_url: str,
    method: str,
    path: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Call one provider-owned fixed path through the ERP outbound policy."""
    target = validate_erp_base_url(base_url)
    if not path.startswith("/") or "\\" in path or "\r" in path or "\n" in path:
        raise OutboundPolicyError("erp_request_path_invalid")
    if any(part in {".", ".."} for part in path.split("?", 1)[0].split("/")):
        raise OutboundPolicyError("erp_request_path_traversal")

    request_path = f"{target.base_path}{path}" if target.base_path else path
    connection_type = _PinnedHTTPSConnection if target.scheme == "https" else _PinnedHTTPConnection
    connection = connection_type(target)
    request_headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "GuardianAI-ERP-Connector/1",
        **headers,
    }
    try:
        connection.request(method.upper(), request_path, headers=request_headers)
        response = connection.getresponse()
        status = response.status
        body = _read_bounded(response)
        if status < 200 or status >= 300:
            raise ValueError(f"ERP provider returned HTTP {status}.")
        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("ERP provider returned an invalid JSON response.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("ERP provider returned an unexpected response shape.")
        return parsed
    finally:
        connection.close()
