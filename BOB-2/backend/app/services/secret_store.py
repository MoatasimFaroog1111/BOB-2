from __future__ import annotations

import hashlib
import os
import re
import threading
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import AuditLog, Organization, User
from app.models.tenant_secret import TenantSecretBinding, TenantSecretVersion
from app.security.audit_chain import utc_naive
from app.services.azure_secret_provider import (
    AzureKeyVaultSecretProvider,
    _bounded_json_response,
    _managed_identity_token,
    _validate_local_identity_endpoint,
    _validate_vault_url,
)
from app.services.encrypted_secret_provider import EncryptedDatabaseSecretProvider
from app.services.secret_provider_types import (
    RemoteSecretVersion,
    SecretNotConfigured,
    SecretProvider,
    SecretStoreError,
)

ALLOWED_SECRET_PURPOSES = frozenset(
    {
        "telegram_bot_token",
        "external_llm_api_key",
        "erp_credentials",
        "totp_secret",
    }
)
_SECRET_NAME_PATTERN = re.compile(r"^[0-9A-Za-z-]{1,127}$")
_MEMORY_VALUES: dict[tuple[str, str], str] = {}
_MEMORY_LOCK = threading.RLock()
_PROVIDER_LOCK = threading.RLock()
_PROVIDER: SecretProvider | None = None


class DisabledSecretProvider:
    provider_name = "disabled"

    def _deny(self) -> None:
        raise SecretStoreError("secret_store_disabled")

    def set_secret(
        self,
        name: str,
        value: str,
        *,
        tags: dict[str, str],
    ) -> RemoteSecretVersion:
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

    def set_secret(
        self,
        name: str,
        value: str,
        *,
        tags: dict[str, str],
    ) -> RemoteSecretVersion:
        if not _SECRET_NAME_PATTERN.fullmatch(name):
            raise SecretStoreError("secret_name_invalid")
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


def get_secret_provider() -> SecretProvider:
    global _PROVIDER
    with _PROVIDER_LOCK:
        if _PROVIDER is not None:
            return _PROVIDER
        configured = settings.SECRET_STORE_PROVIDER.strip().lower()
        if configured == "azure_key_vault":
            _PROVIDER = AzureKeyVaultSecretProvider()
        elif configured == "encrypted_db":
            _PROVIDER = EncryptedDatabaseSecretProvider()
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


def _validate_context(
    db: Session,
    organization_id: int,
    actor_user_id: int | None,
) -> None:
    organization = (
        db.query(Organization)
        .filter(Organization.id == organization_id)
        .first()
    )
    if organization is None or not organization.is_active:
        raise SecretStoreError("secret_store_organization_invalid")
    if actor_user_id is not None:
        user = db.query(User).filter(User.id == actor_user_id).first()
        if (
            user is None
            or not user.is_active
            or user.organization_id != organization_id
        ):
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
                "secret_name_hash": hashlib.sha256(
                    binding.secret_name.encode()
                ).hexdigest(),
                "version_hash": hashlib.sha256(
                    binding.current_version.encode()
                ).hexdigest(),
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
    if (
        not clean
        or len(clean.encode("utf-8"))
        > settings.SECRET_STORE_MAX_REQUEST_BYTES
    ):
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
    now = utc_naive()
    name = binding.secret_name if binding else _secret_name(
        organization_id,
        normalized,
    )
    remote = provider.set_secret(
        name,
        clean,
        tags={
            "organization_id": str(organization_id),
            "purpose": normalized,
        },
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


def secret_is_configured(
    db: Session,
    *,
    organization_id: int,
    purpose: str,
) -> bool:
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
    now = utc_naive()
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


def binding_status(
    db: Session,
    *,
    organization_id: int,
    purpose: str,
) -> TenantSecretBinding | None:
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
    return (
        f"secretref://{binding.provider}/"
        f"{binding.secret_name}/{binding.current_version}"
    )


def resolve_secret_reference(reference: str) -> str:
    try:
        parsed = urlsplit(reference)
    except ValueError as exc:
        raise SecretStoreError("secret_reference_invalid") from exc
    parts = parsed.path.strip("/").split("/")
    provider_name = parsed.netloc
    if (
        parsed.scheme != "secretref"
        or len(parts) != 2
        or parsed.query
        or parsed.fragment
    ):
        raise SecretStoreError("secret_reference_invalid")
    provider = get_secret_provider()
    if provider_name != provider.provider_name:
        raise SecretStoreError("secret_provider_mismatch")
    return provider.get_secret(parts[0], parts[1])


__all__ = [
    "ALLOWED_SECRET_PURPOSES",
    "AzureKeyVaultSecretProvider",
    "EncryptedDatabaseSecretProvider",
    "MemorySecretProvider",
    "RemoteSecretVersion",
    "SecretNotConfigured",
    "SecretProvider",
    "SecretStoreError",
    "binding_status",
    "get_secret_provider",
    "get_tenant_secret",
    "put_tenant_secret",
    "reset_secret_provider_for_tests",
    "resolve_secret_reference",
    "revoke_tenant_secret",
    "secret_is_configured",
    "secret_reference",
    "_bounded_json_response",
    "_managed_identity_token",
    "_validate_local_identity_endpoint",
    "_validate_vault_url",
]
