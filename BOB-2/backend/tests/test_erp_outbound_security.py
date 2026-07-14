"""Adversarial regression tests for ERP SSRF and egress controls."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app.core.config import settings
from app.erp.odoo_transport import PinnedSafeTransport, PinnedTransport
from app.security.outbound_network import (
    OutboundPolicyError,
    ValidatedOutboundTarget,
    validate_erp_base_url,
)


def _resolver(*addresses: str):
    def resolve(_host, port, _family, _socket_type):
        rows = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            rows.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
        return rows

    return resolve


def _public_policy(monkeypatch, *, hosts: str = "odoo.example.com", ports: str = "443"):
    monkeypatch.setattr(settings, "ERP_OUTBOUND_REQUIRE_ALLOWLIST", True)
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_HOSTS", hosts)
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_PORTS", ports)
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_CIDRS", "")
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOW_HTTP", False)


def test_public_allowlisted_url_is_normalized(monkeypatch):
    _public_policy(monkeypatch)
    target = validate_erp_base_url(
        "https://Odoo.Example.com/tenant/",
        resolver=_resolver("93.184.216.34"),
    )
    assert target.normalized_url == "https://odoo.example.com/tenant"
    assert target.hostname == "odoo.example.com"
    assert target.port == 443
    assert target.resolved_ips == ("93.184.216.34",)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (" file:///etc/passwd", "erp_url_invalid"),
        ("file:///etc/passwd", "erp_url_scheme_forbidden"),
        ("ftp://odoo.example.com", "erp_url_scheme_forbidden"),
        ("http://odoo.example.com", "erp_plain_http_forbidden"),
        ("https://user:password@odoo.example.com", "erp_url_userinfo_forbidden"),
        ("https://odoo.example.com?next=http://127.0.0.1", "erp_url_query_or_fragment_forbidden"),
        ("https://odoo.example.com#fragment", "erp_url_query_or_fragment_forbidden"),
        ("https://odoo.example.com/a/../b", "erp_url_path_traversal"),
        ("https://odoo.example.com/%2e%2e/private", "erp_url_path_invalid"),
        ("https://odoo.example.com:8443", "erp_port_not_allowlisted"),
        ("https://not-allowed.example.net", "erp_host_not_allowlisted"),
    ],
)
def test_malformed_or_unapproved_destinations_are_rejected(monkeypatch, url, reason):
    _public_policy(monkeypatch)
    with pytest.raises(OutboundPolicyError) as exc:
        validate_erp_base_url(url, resolver=_resolver("93.184.216.34"))
    assert exc.value.reason == reason


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("127.0.0.1", "erp_special_use_address_blocked"),
        ("0.0.0.0", "erp_special_use_address_blocked"),
        ("169.254.169.254", "erp_cloud_metadata_address_blocked"),
        ("169.254.170.2", "erp_cloud_metadata_address_blocked"),
        ("168.63.129.16", "erp_cloud_metadata_address_blocked"),
        ("10.20.30.40", "erp_private_address_not_allowlisted"),
        ("192.168.1.50", "erp_private_address_not_allowlisted"),
        ("::1", "erp_special_use_address_blocked"),
        ("fe80::1", "erp_special_use_address_blocked"),
        ("fc00::10", "erp_private_address_not_allowlisted"),
        ("::ffff:127.0.0.1", "erp_special_use_address_blocked"),
    ],
)
def test_special_private_and_metadata_addresses_are_blocked(monkeypatch, address, reason):
    _public_policy(monkeypatch)
    with pytest.raises(OutboundPolicyError) as exc:
        validate_erp_base_url("https://odoo.example.com", resolver=_resolver(address))
    assert exc.value.reason == reason


def test_dns_answer_set_fails_if_any_address_is_private(monkeypatch):
    _public_policy(monkeypatch)
    with pytest.raises(OutboundPolicyError) as exc:
        validate_erp_base_url(
            "https://odoo.example.com",
            resolver=_resolver("93.184.216.34", "10.0.0.8"),
        )
    assert exc.value.reason == "erp_private_address_not_allowlisted"


def test_explicit_private_host_and_cidr_are_both_required(monkeypatch):
    _public_policy(monkeypatch, hosts="odoo.internal.example")
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_CIDRS", "10.20.30.0/24")
    target = validate_erp_base_url(
        "https://odoo.internal.example",
        resolver=_resolver("10.20.30.40"),
    )
    assert target.resolved_ips == ("10.20.30.40",)

    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_HOSTS", "other.internal.example")
    with pytest.raises(OutboundPolicyError) as exc:
        validate_erp_base_url(
            "https://odoo.internal.example",
            resolver=_resolver("10.20.30.40"),
        )
    assert exc.value.reason == "erp_host_not_allowlisted"


def test_broad_or_non_private_cidr_cannot_override_policy(monkeypatch):
    _public_policy(monkeypatch)
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_CIDRS", "0.0.0.0/0")
    with pytest.raises(OutboundPolicyError) as exc:
        validate_erp_base_url(
            "https://odoo.example.com",
            resolver=_resolver("10.20.30.40"),
        )
    assert exc.value.reason == "erp_allowed_cidr_not_private"


def test_wildcard_matches_only_subdomains_and_global_wildcard_is_forbidden(monkeypatch):
    _public_policy(monkeypatch, hosts="*.trusted.example")
    target = validate_erp_base_url(
        "https://odoo.trusted.example",
        resolver=_resolver("93.184.216.34"),
    )
    assert target.hostname == "odoo.trusted.example"

    with pytest.raises(OutboundPolicyError) as apex:
        validate_erp_base_url(
            "https://trusted.example",
            resolver=_resolver("93.184.216.34"),
        )
    assert apex.value.reason == "erp_host_not_allowlisted"

    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_HOSTS", "*")
    with pytest.raises(OutboundPolicyError) as global_wildcard:
        validate_erp_base_url(
            "https://odoo.trusted.example",
            resolver=_resolver("93.184.216.34"),
        )
    assert global_wildcard.value.reason == "erp_wildcard_allowlist_forbidden"


def test_numeric_loopback_hostname_is_still_blocked_after_resolution(monkeypatch):
    _public_policy(monkeypatch, hosts="2130706433")
    with pytest.raises(OutboundPolicyError) as exc:
        validate_erp_base_url(
            "https://2130706433",
            resolver=_resolver("127.0.0.1"),
        )
    assert exc.value.reason == "erp_special_use_address_blocked"


def _target(scheme: str = "https") -> ValidatedOutboundTarget:
    return ValidatedOutboundTarget(
        normalized_url=f"{scheme}://odoo.example.com",
        scheme=scheme,
        hostname="odoo.example.com",
        port=443 if scheme == "https" else 80,
        base_path="",
        resolved_ips=("93.184.216.34",),
    )


def test_transport_revalidates_each_connection_and_pins_validated_ip(monkeypatch):
    calls: list[str] = []

    def validate(url):
        calls.append(url)
        return _target()

    monkeypatch.setattr("app.erp.odoo_transport.validate_erp_base_url", validate)
    transport = PinnedSafeTransport("https://odoo.example.com")
    first = transport.make_connection("odoo.example.com")
    second = transport.make_connection("odoo.example.com:443")

    assert calls == ["https://odoo.example.com", "https://odoo.example.com"]
    assert first.host == "odoo.example.com"
    assert first._target.resolved_ips == ("93.184.216.34",)
    assert second._target.port == 443


def test_transport_rejects_server_proxy_host_mismatch(monkeypatch):
    monkeypatch.setattr("app.erp.odoo_transport.validate_erp_base_url", lambda _url: _target())
    transport = PinnedSafeTransport("https://odoo.example.com")
    with pytest.raises(OutboundPolicyError) as exc:
        transport.make_connection("127.0.0.1:443")
    assert exc.value.reason == "erp_xmlrpc_host_mismatch"


class _FakeResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None):
        self.chunks = list(chunks)
        self.headers = headers or {}
        self.closed = False

    def getheader(self, name: str, default=None):
        return self.headers.get(name, default)

    def read(self, _size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def close(self) -> None:
        self.closed = True


class _FakeParser:
    def feed(self, _chunk: bytes) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeUnmarshaller:
    def close(self):
        return {"ok": True}


def test_xmlrpc_response_stream_has_hard_byte_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "ERP_OUTBOUND_MAX_RESPONSE_BYTES", 5)
    transport = PinnedTransport("http://odoo.example.com")
    monkeypatch.setattr(transport, "getparser", lambda: (_FakeParser(), _FakeUnmarshaller()))
    response = _FakeResponse([b"1234", b"56"])
    with pytest.raises(OutboundPolicyError) as exc:
        transport.parse_response(response)
    assert exc.value.reason == "erp_response_too_large"
    assert response.closed is True


def test_xmlrpc_declared_response_size_is_rejected_before_read(monkeypatch):
    monkeypatch.setattr(settings, "ERP_OUTBOUND_MAX_RESPONSE_BYTES", 5)
    transport = PinnedSafeTransport("https://odoo.example.com")
    response = _FakeResponse([], {"Content-Length": "6"})
    with pytest.raises(OutboundPolicyError) as exc:
        transport.parse_response(response)
    assert exc.value.reason == "erp_response_too_large"
    assert response.closed is True


def test_production_erp_policy_configuration_is_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "ERP_OUTBOUND_REQUIRE_ALLOWLIST", False)
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOWED_HOSTS", "")
    monkeypatch.setattr(settings, "ERP_OUTBOUND_ALLOW_HTTP", True)
    errors: list[str] = []
    settings._validate_erp_outbound_configuration(errors)
    assert "ERP_OUTBOUND_REQUIRE_ALLOWLIST must be true" in errors
    assert "ERP_OUTBOUND_ALLOWED_HOSTS is required" in errors
    assert "ERP_OUTBOUND_ALLOW_HTTP must be false in production" in errors


def test_odoo_provider_cannot_return_to_default_unpinned_serverproxy():
    provider_source = Path("app/erp/providers/odoo.py").read_text(encoding="utf-8")
    transport_source = Path("app/erp/odoo_transport.py").read_text(encoding="utf-8")
    assert "xmlrpc.client.ServerProxy" not in provider_source
    assert "create_odoo_server_proxies" in provider_source
    assert "socket.create_connection" in transport_source
    assert "server_hostname=self._target.hostname" in transport_source
    assert "ERP_OUTBOUND_MAX_RESPONSE_BYTES" in transport_source
