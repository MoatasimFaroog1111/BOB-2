"""DNS-pinned, timeout-bounded XML-RPC transport for Odoo."""

from __future__ import annotations

import http.client
import socket
import ssl
import xmlrpc.client
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings
from app.security.outbound_network import (
    OutboundPolicyError,
    ValidatedOutboundTarget,
    validate_erp_base_url,
)


def _connect_validated_socket(
    target: ValidatedOutboundTarget,
    *,
    timeout: float,
    source_address: tuple[str, int] | None,
) -> socket.socket:
    last_error: OSError | None = None
    for address in target.resolved_ips:
        try:
            return socket.create_connection(
                (address, target.port),
                timeout=timeout,
                source_address=source_address,
            )
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
        self.sock = _connect_validated_socket(
            self._target,
            timeout=float(settings.ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS),
            source_address=self.source_address,
        )
        self.sock.settimeout(float(settings.ERP_OUTBOUND_READ_TIMEOUT_SECONDS))


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
        raw_socket = _connect_validated_socket(
            self._target,
            timeout=float(settings.ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS),
            source_address=self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._target.hostname,
            )
            self.sock.settimeout(float(settings.ERP_OUTBOUND_READ_TIMEOUT_SECONDS))
        except Exception:
            raw_socket.close()
            raise


class _BoundedXMLRPCResponseMixin:
    def parse_response(self, response: http.client.HTTPResponse) -> Any:
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

        stream: Any = response
        if response.getheader("Content-Encoding", "") == "gzip":
            stream = xmlrpc.client.GzipDecodedResponse(response)

        parser, unmarshaller = self.getparser()
        total = 0
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.ERP_OUTBOUND_MAX_RESPONSE_BYTES:
                    raise OutboundPolicyError("erp_response_too_large")
                parser.feed(chunk)
            parser.close()
            return unmarshaller.close()
        finally:
            try:
                stream.close()
            finally:
                response.close()


class PinnedSafeTransport(_BoundedXMLRPCResponseMixin, xmlrpc.client.SafeTransport):
    def __init__(self, base_url: str) -> None:
        super().__init__(use_builtin_types=True)
        self._base_url = base_url

    def make_connection(self, host: str) -> _PinnedHTTPSConnection:
        target = validate_erp_base_url(self._base_url)
        _verify_xmlrpc_host(host, target)
        return _PinnedHTTPSConnection(target)


class PinnedTransport(_BoundedXMLRPCResponseMixin, xmlrpc.client.Transport):
    def __init__(self, base_url: str) -> None:
        super().__init__(use_builtin_types=True)
        self._base_url = base_url

    def make_connection(self, host: str) -> _PinnedHTTPConnection:
        target = validate_erp_base_url(self._base_url)
        _verify_xmlrpc_host(host, target)
        return _PinnedHTTPConnection(target)


def _verify_xmlrpc_host(host: str, target: ValidatedOutboundTarget) -> None:
    try:
        parsed = urlsplit("//" + host)
        hostname = (parsed.hostname or "").rstrip(".").lower().encode("idna").decode("ascii")
        port = parsed.port or (443 if target.scheme == "https" else 80)
    except (ValueError, UnicodeError) as exc:
        raise OutboundPolicyError("erp_xmlrpc_host_invalid") from exc
    if hostname != target.hostname or port != target.port:
        raise OutboundPolicyError("erp_xmlrpc_host_mismatch")


def create_odoo_server_proxies(
    base_url: str,
) -> tuple[ValidatedOutboundTarget, xmlrpc.client.ServerProxy, xmlrpc.client.ServerProxy]:
    """Return normalized target plus isolated common/object proxies."""

    target = validate_erp_base_url(base_url)
    transport_type = PinnedSafeTransport if target.scheme == "https" else PinnedTransport
    common = xmlrpc.client.ServerProxy(
        f"{target.normalized_url}/xmlrpc/2/common",
        transport=transport_type(target.normalized_url),
        allow_none=True,
        use_builtin_types=True,
    )
    models = xmlrpc.client.ServerProxy(
        f"{target.normalized_url}/xmlrpc/2/object",
        transport=transport_type(target.normalized_url),
        allow_none=True,
        use_builtin_types=True,
    )
    return target, common, models
