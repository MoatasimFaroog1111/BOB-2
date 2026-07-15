from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import AuditLog, Organization, User
from app.models.tenant_secret import TenantSecretBinding, TenantSecretVersion

ALLOWED_SECRET_PURPOSES = frozenset(
    {
        "telegram_bot_token",
        "external_llm_api_key",
        "erp_credentials",
    }
)
_SECRET_NAME_PATTERN = re.compile(r"^[0-9A-Za-z-]{1,127}$")
_MEMORY_VALUES: dict[tuple[str, str], str] = {}
_MEMORY_LOCK = threading.RLock()
_PROVIDER_LOCK = threading.RLock()
_PROVIDER: SecretProvider | None = None


class SecretStoreError(RuntimeError):
    def __init__(self, reason: str, public_message: str = "The secure secret store operation failed.") -> None:
        super().__init__(public_message)
        self.reason = reason
        self.public_message = public_message


class SecretNotConfigured(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("secret_not_configured", "The requested secret is not configured.")


@dataclass(frozen=True, slots=True)
class RemoteSecretVersion:
    name: str
    version: str


class SecretProvider(Protocol):
    provider_name: str

    def set_secret(self, name: str, value: str, *, tags: dict[str, str]) -> RemoteSecretVersion: ...

    def get_secret(self, name: str, version: str) -> str: ...

    def disable_secret(self, name: str, version: str) -> None: ...


class DisabledSecretProvider:
    provider_name = "disabled"

    def _deny(self) -> None:
        raise SecretStoreError("secret_store_disabled")

    def set_secret(self, name: str, value: str, *, tags: dict[str, str]) -> RemoteSecretVersion:
        self._deny()

    def get_secret(self, name: str, version: str) -> str:
        self._deny()

    def disable_secret(self, name: str, version: str) -> None:
        self._deny()


class MemorySecretProvider:
    provider_name = "memory"

    def __init__(self) -> None:
        if settings.is_production:
            raise SecretStoreError("memory_secret_store_forbidden_in_production")

    def set_secret(self, name: str, value: str, *, tags: dict[str, str]) -> RemoteSecretVersion:
        version = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
        with _MEMORY_LOCK:
            _MEMORY_VALUES[(name, version)] = value
        return RemoteSecretVersion(name=name, version=version)

    def get_secret(self, name: str, version: str) -> str:
        with _MEMORY_LOCK:
            try:
                return _MEMORY_VALUES[(name, version)]
            except KeyError as exc:
                raise SecretStoreError("memory_secret_version_missing") from exc

    def disable_secret(self, name: str, version: str) -> None:
        with _MEMORY_LOCK:
            _MEMORY_VALUES.pop((name, version), None)


@dataclass(frozen=True, slots=True)
class _ValidatedVault:
    url: str
    hostname: str
    addresses: tuple[str, ...]


def _bounded_json_response(response: http.client.HTTPResponse, *, max_bytes: int) -> dict[str, Any]:
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
    return _ValidatedVault(url=f"https://{hostname}", hostname=hostname, addresses=tuple(addresses))


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
                self.sock = self._context.wrap_socket(sock, server_hostname=self._vault.hostname)
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

    def set_secret(self, name: str, value: str, *, tags: dict[str, str]) -> RemoteSecretVersion:
        if not _SECRET_NAME_PATTERN.fullmatch(name):
            raise SecretStoreError("secret_name_invalid")
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
        if not _SECRET_NAME_PATTERN.fullmatch(name) or not version:
            raise SecretStoreError("secret_reference_invalid")
        payload = self._request(
            "GET",
            f"/secrets/{quote(name)}/{quote(version)}?api-version=7.4",
        )
        value = payload.get("value")
        if not isinstance(value, str) or not value:
            raise SecretStoreError("azure_key_vault_value_missing")
        return value

    def disable_secret(self, name: str, version: str) -> None:
        if not _SECRET_NAME_PATTERN.fullmatch(name) or not version:
            raise SecretStoreError("secret_reference_invalid")
        self._request(
            "PATCH",
            f"/secrets/{quote(name)}/{quote(version)}?api-version=7.4",
            body={"attributes": {"enabled": False}},
        )


def get_secret_provider() -> SecretProvider:
    global _PROVIDER
    with _PROVIDER_LOCK:
        if _PROVIDER is not None:
            return _PROVIDER
        configured = settings.SECRET_STORE_PROVIDER.strip().lower()
        if configured == "azure_key_vault":
            _PROVIDER = AzureKeyVaultSecretProvider()
        elif configured == "memory":
            _PROVIDER = MemorySecretProvider()
        elif configured == "disabled":
            _PROVIDER = DisabledSecretProvider()
        else:
            raise SecretStoreError("secret_store_provider_invalid")
        return _PROVIDER


def reset_secret_provider_for_tests() -> None:
    global _PROVIDER
    if settings.is_production:
        raise RuntimeError("Secret provider reset is forbidden in production")
    with _PROVIDER_LOCK, _MEMORY_LOCK:
        _PROVIDER = None
        _MEMORY_VALUES.clear()


def _validate_context(db: Session, organization_id: int, actor_user_id: int | None) -> None:
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if organization is None or not organization.is_active:
        raise SecretStoreError("secret_store_organization_invalid")
    if actor_user_id is not None:
        user = db.query(User).filter(User.id == actor_user_id).first()
        if user is None or not user.is_active or user.organization_id != organization_id:
            raise SecretStoreError("secret_store_actor_invalid")


def _validate_purpose(purpose: str) -> str:
    normalized = purpose.strip().lower()
    if normalized not in ALLOWED_SECRET_PURPOSES:
        raise SecretStoreError("secret_purpose_invalid")
    return normalized


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _secret_name(organization_id: int, purpose: str) -> str:
    suffix = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
    return f"org-{organization_id}-{purpose.replace('_', '-')}-{suffix}"[:127]


def _audit(
    db: Session,
    *,
    organization_id: int,
    actor_user_id: int | None,
    action: str,
    binding: TenantSecretBinding,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=organization_id,
            user_id=actor_user_id,
            action=action,
            entity_type="tenant_secret",
            entity_id=str(binding.id),
            details={
                "purpose": binding.purpose,
                "provider": binding.provider,
                "secret_name_hash": hashlib.sha256(binding.secret_name.encode()).hexdigest(),
                "version_hash": hashlib.sha256(binding.current_version.encode()).hexdigest(),
                "fingerprint_sha256": binding.fingerprint_sha256,
                **(details or {}),
            },
        )
    )


def put_tenant_secret(
    db: Session,
    *,
    organization_id: int,
    actor_user_id: int | None,
    purpose: str,
    value: str,
) -> TenantSecretBinding:
    normalized = _validate_purpose(purpose)
    clean = value.strip()
    if not clean or len(clean.encode("utf-8")) > settings.SECRET_STORE_MAX_REQUEST_BYTES:
        raise SecretStoreError("secret_value_invalid")
    _validate_context(db, organization_id, actor_user_id)
    provider = get_secret_provider()
    if provider.provider_name == "disabled":
        raise SecretStoreError("secret_store_disabled")
    binding = (
        db.query(TenantSecretBinding)
        .filter(
            TenantSecretBinding.organization_id == organization_id,
            TenantSecretBinding.purpose == normalized,
        )
        .with_for_update()
        .first()
    )
    now = datetime.utcnow()
    name = binding.secret_name if binding else _secret_name(organization_id, normalized)
    remote = provider.set_secret(
        name,
        clean,
        tags={"organization_id": str(organization_id), "purpose": normalized},
    )
    digest = _fingerprint(clean)
    if binding is None:
        binding = TenantSecretBinding(
            organization_id=organization_id,
            purpose=normalized,
            provider=provider.provider_name,
            secret_name=remote.name,
            current_version=remote.version,
            status="active",
            fingerprint_sha256=digest,
            created_by_user_id=actor_user_id,
            rotated_by_user_id=actor_user_id,
            last_rotated_at=now,
        )
        db.add(binding)
        db.flush()
        action = "tenant_secret_created"
    else:
        previous = (
            db.query(TenantSecretVersion)
            .filter(
                TenantSecretVersion.binding_id == binding.id,
                TenantSecretVersion.status == "active",
            )
            .first()
        )
        if previous:
            previous.status = "superseded"
            previous.superseded_at = now
        binding.provider = provider.provider_name
        binding.current_version = remote.version
        binding.status = "active"
        binding.fingerprint_sha256 = digest
        binding.rotated_by_user_id = actor_user_id
        binding.last_rotated_at = now
        binding.revoked_by_user_id = None
        binding.revoked_at = None
        action = "tenant_secret_rotated"
    db.add(
        TenantSecretVersion(
            binding_id=binding.id,
            organization_id=organization_id,
            purpose=normalized,
            provider=provider.provider_name,
            secret_name=remote.name,
            version=remote.version,
            fingerprint_sha256=digest,
            status="active",
            created_by_user_id=actor_user_id,
        )
    )
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        binding=binding,
    )
    try:
        db.commit()
        db.refresh(binding)
    except Exception:
        db.rollback()
        try:
            provider.disable_secret(remote.name, remote.version)
        except Exception:
            pass
        raise
    return binding


def get_tenant_secret(
    db: Session,
    *,
    organization_id: int,
    purpose: str,
) -> str:
    normalized = _validate_purpose(purpose)
    binding = (
        db.query(TenantSecretBinding)
        .filter(
            TenantSecretBinding.organization_id == organization_id,
            TenantSecretBinding.purpose == normalized,
            TenantSecretBinding.status == "active",
        )
        .first()
    )
    if binding is None or binding.revoked_at is not None:
        raise SecretNotConfigured()
    provider = get_secret_provider()
    if binding.provider != provider.provider_name:
        raise SecretStoreError("secret_provider_mismatch")
    value = provider.get_secret(binding.secret_name, binding.current_version)
    if _fingerprint(value) != binding.fingerprint_sha256:
        raise SecretStoreError("secret_fingerprint_mismatch")
    return value


def secret_is_configured(db: Session, *, organization_id: int, purpose: str) -> bool:
    normalized = _validate_purpose(purpose)
    return (
        db.query(TenantSecretBinding.id)
        .filter(
            TenantSecretBinding.organization_id == organization_id,
            TenantSecretBinding.purpose == normalized,
            TenantSecretBinding.status == "active",
            TenantSecretBinding.revoked_at.is_(None),
        )
        .first()
        is not None
    )


def revoke_tenant_secret(
    db: Session,
    *,
    organization_id: int,
    actor_user_id: int | None,
    purpose: str,
) -> TenantSecretBinding | None:
    normalized = _validate_purpose(purpose)
    _validate_context(db, organization_id, actor_user_id)
    binding = (
        db.query(TenantSecretBinding)
        .filter(
            TenantSecretBinding.organization_id == organization_id,
            TenantSecretBinding.purpose == normalized,
        )
        .with_for_update()
        .first()
    )
    if binding is None:
        return None
    provider = get_secret_provider()
    provider.disable_secret(binding.secret_name, binding.current_version)
    now = datetime.utcnow()
    binding.status = "revoked"
    binding.revoked_by_user_id = actor_user_id
    binding.revoked_at = now
    current = (
        db.query(TenantSecretVersion)
        .filter(
            TenantSecretVersion.binding_id == binding.id,
            TenantSecretVersion.version == binding.current_version,
        )
        .first()
    )
    if current:
        current.status = "revoked"
        current.revoked_at = now
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="tenant_secret_revoked",
        binding=binding,
    )
    db.commit()
    db.refresh(binding)
    return binding


def binding_status(db: Session, *, organization_id: int, purpose: str) -> TenantSecretBinding | None:
    normalized = _validate_purpose(purpose)
    return (
        db.query(TenantSecretBinding)
        .filter(
            TenantSecretBinding.organization_id == organization_id,
            TenantSecretBinding.purpose == normalized,
        )
        .first()
    )


def secret_reference(binding: TenantSecretBinding) -> str:
    return f"secretref://{binding.provider}/{binding.secret_name}/{binding.current_version}"


def resolve_secret_reference(reference: str) -> str:
    try:
        parsed = urlsplit(reference)
    except ValueError as exc:
        raise SecretStoreError("secret_reference_invalid") from exc
    parts = parsed.path.strip("/").split("/")
    provider_name = parsed.netloc
    if parsed.scheme != "secretref" or len(parts) != 2 or parsed.query or parsed.fragment:
        raise SecretStoreError("secret_reference_invalid")
    provider = get_secret_provider()
    if provider_name != provider.provider_name:
        raise SecretStoreError("secret_provider_mismatch")
    return provider.get_secret(parts[0], parts[1])
