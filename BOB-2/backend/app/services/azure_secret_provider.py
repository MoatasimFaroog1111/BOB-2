from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from app.core.config import settings
from app.services.secret_provider_types import RemoteSecretVersion, SecretStoreError


@dataclass(frozen=True, slots=True)
class _ValidatedVault:
    url: str
    hostname: str
    addresses: tuple[str, ...]


def _bounded_json_response(
    response: http.client.HTTPResponse,
    *,
    max_bytes: int,
) -> dict[str, Any]:
    declared = response.getheader("Content-Length")
    if declared:
        try:
            if int(declared) > max_bytes:
                raise SecretStoreError("secret_store_response_too_large")
        except ValueError as exc:
            raise SecretStoreError("secret_store_response_length_invalid") from exc
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise SecretStoreError("secret_store_response_too_large")
            chunks.append(chunk)
    finally:
        response.close()
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecretStoreError("secret_store_response_invalid_json") from exc
    if not isinstance(payload, dict):
        raise SecretStoreError("secret_store_response_invalid_shape")
    return payload


def _validate_vault_url(raw_url: str) -> _ValidatedVault:
    try:
        parsed = urlsplit(raw_url)
    except ValueError as exc:
        raise SecretStoreError("azure_key_vault_url_invalid") from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() != "https"
        or not hostname.endswith(".vault.azure.net")
        or hostname.count(".") < 3
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SecretStoreError("azure_key_vault_url_invalid")
    try:
        resolved = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SecretStoreError("azure_key_vault_dns_failed") from exc
    addresses: list[str] = []
    for item in resolved:
        address = ipaddress.ip_address(item[4][0])
        if (
            not address.is_global
            or address.is_loopback
            or address.is_link_local
            or address.is_private
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise SecretStoreError("azure_key_vault_address_blocked")
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise SecretStoreError("azure_key_vault_dns_empty")
    return _ValidatedVault(
        url=f"https://{hostname}",
        hostname=hostname,
        addresses=tuple(addresses),
    )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, vault: _ValidatedVault) -> None:
        super().__init__(
            vault.hostname,
            port=443,
            timeout=settings.SECRET_STORE_CONNECT_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
        self._vault = vault

    def connect(self) -> None:
        last_error: OSError | None = None
        for address in self._vault.addresses:
            try:
                sock = socket.create_connection(
                    (address, 443),
                    timeout=settings.SECRET_STORE_CONNECT_TIMEOUT_SECONDS,
                )
                sock.settimeout(settings.SECRET_STORE_READ_TIMEOUT_SECONDS)
                self.sock = self._context.wrap_socket(
                    sock,
                    server_hostname=self._vault.hostname,
                )
                return
            except OSError as exc:
                last_error = exc
        raise SecretStoreError("azure_key_vault_connection_failed") from last_error

    def set_tunnel(self, *args: Any, **kwargs: Any) -> None:
        raise SecretStoreError("azure_key_vault_proxy_tunnel_forbidden")


def _validate_local_identity_endpoint(value: str) -> tuple[str, int, str]:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise SecretStoreError("managed_identity_endpoint_invalid") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SecretStoreError("managed_identity_endpoint_invalid")
    path = parsed.path or "/MSI/token"
    return host, parsed.port, path


def _managed_identity_token() -> str:
    endpoint = os.getenv("IDENTITY_ENDPOINT", "").strip()
    identity_header = os.getenv("IDENTITY_HEADER", "").strip()
    client_id = settings.AZURE_MANAGED_IDENTITY_CLIENT_ID.strip()
    query = {
        "api-version": "2019-08-01",
        "resource": "https://vault.azure.net",
    }
    if client_id:
        query["client_id"] = client_id

    if endpoint and identity_header:
        host, port, path = _validate_local_identity_endpoint(endpoint)
        connection = http.client.HTTPConnection(
            host,
            port,
            timeout=settings.SECRET_STORE_CONNECT_TIMEOUT_SECONDS,
        )
        headers = {"X-IDENTITY-HEADER": identity_header, "Metadata": "true"}
    else:
        host, port, path = "169.254.169.254", 80, "/metadata/identity/oauth2/token"
        query["api-version"] = "2018-02-01"
        connection = http.client.HTTPConnection(
            host,
            port,
            timeout=settings.SECRET_STORE_CONNECT_TIMEOUT_SECONDS,
        )
        headers = {"Metadata": "true"}

    try:
        connection.request("GET", f"{path}?{urlencode(query)}", headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            response.close()
            raise SecretStoreError("managed_identity_token_failed")
        payload = _bounded_json_response(
            response,
            max_bytes=settings.SECRET_STORE_MAX_RESPONSE_BYTES,
        )
    except (OSError, http.client.HTTPException) as exc:
        raise SecretStoreError("managed_identity_transport_failed") from exc
    finally:
        connection.close()
    token = payload.get("access_token")
    if not isinstance(token, str) or len(token) < 32:
        raise SecretStoreError("managed_identity_token_invalid")
    return token


class AzureKeyVaultSecretProvider:
    provider_name = "azure_key_vault"

    def __init__(self) -> None:
        self.vault = _validate_vault_url(settings.AZURE_KEY_VAULT_URL)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = _managed_identity_token()
        connection = _PinnedHTTPSConnection(self.vault)
        encoded = b""
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        }
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
            if len(encoded) > settings.SECRET_STORE_MAX_REQUEST_BYTES:
                raise SecretStoreError("secret_store_request_too_large")
        try:
            connection.request(method, path, body=encoded or None, headers=headers)
            response = connection.getresponse()
            if response.status not in {200, 201}:
                response.close()
                raise SecretStoreError(f"azure_key_vault_http_{response.status}")
            return _bounded_json_response(
                response,
                max_bytes=settings.SECRET_STORE_MAX_RESPONSE_BYTES,
            )
        except SecretStoreError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise SecretStoreError("azure_key_vault_transport_failed") from exc
        finally:
            connection.close()

    def set_secret(
        self,
        name: str,
        value: str,
        *,
        tags: dict[str, str],
    ) -> RemoteSecretVersion:
        payload = self._request(
            "PUT",
            f"/secrets/{quote(name)}?api-version=7.4",
            body={"value": value, "attributes": {"enabled": True}, "tags": tags},
        )
        identifier = payload.get("id")
        if not isinstance(identifier, str):
            raise SecretStoreError("azure_key_vault_version_missing")
        parts = urlsplit(identifier).path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "secrets" or parts[1] != name or not parts[2]:
            raise SecretStoreError("azure_key_vault_version_invalid")
        return RemoteSecretVersion(name=name, version=parts[2])

    def get_secret(self, name: str, version: str) -> str:
        payload = self._request(
            "GET",
            f"/secrets/{quote(name)}/{quote(version)}?api-version=7.4",
        )
        value = payload.get("value")
        if not isinstance(value, str) or not value:
            raise SecretStoreError("azure_key_vault_value_missing")
        return value

    def disable_secret(self, name: str, version: str) -> None:
        self._request(
            "PATCH",
            f"/secrets/{quote(name)}/{quote(version)}?api-version=7.4",
            body={"attributes": {"enabled": False}},
        )
