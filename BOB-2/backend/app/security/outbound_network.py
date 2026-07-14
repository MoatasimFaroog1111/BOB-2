"""Fail-closed outbound network policy for tenant-configurable ERP destinations.

The policy validates both the configured hostname and every address returned by DNS.
Connections must use a transport that pins one of the validated addresses so DNS cannot
change between policy evaluation and the socket connection.
"""

from __future__ import annotations

import ipaddress
import posixpath
import socket
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings

Resolver = Callable[..., Sequence[tuple]]

_NEVER_ALLOWED_IPS = {
    ipaddress.ip_address("169.254.169.254"),  # cloud instance metadata
    ipaddress.ip_address("169.254.170.2"),    # container/task metadata
    ipaddress.ip_address("168.63.129.16"),    # Azure platform virtual IP
    ipaddress.ip_address("100.100.100.200"),  # Alibaba metadata
}
_PRIVATE_NETWORK_SUPERNETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
)


class OutboundPolicyError(ValueError):
    """Structured denial that is safe to map to a generic client response."""

    def __init__(
        self,
        reason: str,
        public_message: str = "The ERP destination is not allowed by the outbound network policy.",
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.public_message = public_message


@dataclass(frozen=True, slots=True)
class ValidatedOutboundTarget:
    normalized_url: str
    scheme: str
    hostname: str
    port: int
    base_path: str
    resolved_ips: tuple[str, ...]


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _allowed_ports() -> set[int]:
    ports: set[int] = set()
    for raw in _split_csv(settings.ERP_OUTBOUND_ALLOWED_PORTS):
        try:
            port = int(raw)
        except ValueError as exc:
            raise OutboundPolicyError("erp_allowed_port_invalid") from exc
        if not 1 <= port <= 65535:
            raise OutboundPolicyError("erp_allowed_port_invalid")
        ports.add(port)
    if not ports:
        raise OutboundPolicyError("erp_allowed_ports_empty")
    return ports


def _network_is_explicit_private_range(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    return any(
        network.version == supernet.version and network.subnet_of(supernet)
        for supernet in _PRIVATE_NETWORK_SUPERNETS
    )


def _allowed_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in _split_csv(settings.ERP_OUTBOUND_ALLOWED_CIDRS):
        try:
            network = ipaddress.ip_network(raw, strict=True)
        except ValueError as exc:
            raise OutboundPolicyError("erp_allowed_cidr_invalid") from exc
        if not _network_is_explicit_private_range(network):
            raise OutboundPolicyError("erp_allowed_cidr_not_private")
        networks.append(network)
    return tuple(networks)


def _normalize_hostname(hostname: str | None) -> str:
    if not hostname:
        raise OutboundPolicyError("erp_hostname_missing")
    candidate = hostname.rstrip(".").lower()
    if not candidate or any(ord(char) < 33 for char in candidate):
        raise OutboundPolicyError("erp_hostname_invalid")

    try:
        literal = ipaddress.ip_address(candidate)
    except ValueError:
        literal = None
    if literal is not None:
        return str(literal)

    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise OutboundPolicyError("erp_hostname_invalid") from exc
    if len(candidate) > 253 or any(len(label) > 63 or not label for label in candidate.split(".")):
        raise OutboundPolicyError("erp_hostname_invalid")
    return candidate


def _host_matches_pattern(hostname: str, pattern: str) -> bool:
    wildcard = pattern.startswith("*.")
    normalized = _normalize_hostname(pattern.removeprefix("*."))
    if wildcard:
        if ":" in normalized:
            raise OutboundPolicyError("erp_ipv6_wildcard_forbidden")
        return hostname.endswith("." + normalized) and hostname != normalized
    return hostname == normalized


def _host_is_allowlisted(hostname: str) -> bool:
    patterns = _split_csv(settings.ERP_OUTBOUND_ALLOWED_HOSTS)
    if any(pattern == "*" for pattern in patterns):
        raise OutboundPolicyError("erp_wildcard_allowlist_forbidden")
    if not patterns:
        if settings.ERP_OUTBOUND_REQUIRE_ALLOWLIST:
            raise OutboundPolicyError("erp_allowlist_empty")
        return True
    try:
        return any(_host_matches_pattern(hostname, pattern.lower()) for pattern in patterns)
    except OutboundPolicyError:
        raise
    except Exception as exc:
        raise OutboundPolicyError("erp_allowlist_invalid") from exc


def _ip_is_explicitly_allowlisted(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def _validate_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allowed_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address in _NEVER_ALLOWED_IPS:
        raise OutboundPolicyError("erp_cloud_metadata_address_blocked")
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise OutboundPolicyError("erp_special_use_address_blocked")
    if _ip_is_explicitly_allowlisted(address, allowed_networks):
        return
    if address.is_private:
        raise OutboundPolicyError("erp_private_address_not_allowlisted")
    if not address.is_global:
        raise OutboundPolicyError("erp_non_global_address_blocked")


def _resolve_addresses(
    hostname: str,
    port: int,
    resolver: Resolver,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        return (literal,)

    try:
        records = resolver(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise OutboundPolicyError("erp_dns_resolution_failed") from exc

    addresses: dict[str, ipaddress.IPv4Address | ipaddress.IPv6Address] = {}
    for record in records:
        if len(record) < 5 or not record[4]:
            continue
        raw_address = str(record[4][0]).split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(raw_address)
        except ValueError:
            continue
        addresses[str(parsed)] = parsed
    if not addresses:
        raise OutboundPolicyError("erp_dns_no_addresses")
    return tuple(addresses[key] for key in sorted(addresses))


def _normalize_base_path(path: str) -> str:
    if not path or path == "/":
        return ""
    if "\\" in path or "%" in path or "//" in path or any(ord(char) < 32 for char in path):
        raise OutboundPolicyError("erp_url_path_invalid")
    parts = path.split("/")
    if any(part in {".", ".."} for part in parts):
        raise OutboundPolicyError("erp_url_path_traversal")
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/") or normalized.startswith("//"):
        raise OutboundPolicyError("erp_url_path_invalid")
    return normalized.rstrip("/")


def validate_erp_base_url(
    raw_url: str,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> ValidatedOutboundTarget:
    """Validate, normalize, resolve, and authorize one ERP base URL.

    Every DNS answer must pass the address policy. The caller must pin the socket to one
    of ``resolved_ips`` instead of resolving the hostname a second time.
    """

    if not isinstance(raw_url, str):
        raise OutboundPolicyError("erp_url_missing")
    if not raw_url or raw_url != raw_url.strip():
        raise OutboundPolicyError("erp_url_invalid")
    candidate = raw_url
    if any(char in candidate for char in ("\r", "\n", "\t", "\\")):
        raise OutboundPolicyError("erp_url_invalid")

    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise OutboundPolicyError("erp_url_invalid") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"https", "http"}:
        raise OutboundPolicyError("erp_url_scheme_forbidden")
    if scheme == "http" and not settings.ERP_OUTBOUND_ALLOW_HTTP:
        raise OutboundPolicyError("erp_plain_http_forbidden")
    if parsed.username is not None or parsed.password is not None:
        raise OutboundPolicyError("erp_url_userinfo_forbidden")
    if parsed.query or parsed.fragment:
        raise OutboundPolicyError("erp_url_query_or_fragment_forbidden")

    hostname = _normalize_hostname(parsed.hostname)
    if not _host_is_allowlisted(hostname):
        raise OutboundPolicyError("erp_host_not_allowlisted")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise OutboundPolicyError("erp_port_invalid") from exc
    if port not in _allowed_ports():
        raise OutboundPolicyError("erp_port_not_allowlisted")

    base_path = _normalize_base_path(parsed.path)
    allowed_networks = _allowed_networks()
    addresses = _resolve_addresses(hostname, port, resolver)
    for address in addresses:
        _validate_address(address, allowed_networks)

    host_for_url = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    netloc = host_for_url if port == default_port else f"{host_for_url}:{port}"
    normalized_url = urlunsplit((scheme, netloc, base_path, "", ""))
    return ValidatedOutboundTarget(
        normalized_url=normalized_url,
        scheme=scheme,
        hostname=hostname,
        port=port,
        base_path=base_path,
        resolved_ips=tuple(str(address) for address in addresses),
    )
