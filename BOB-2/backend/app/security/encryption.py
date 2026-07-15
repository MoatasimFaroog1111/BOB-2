"""Compatibility bridge for legacy ERP credential callers.

No encryption key or ciphertext is stored locally. New code should call
``app.services.secret_store`` directly. The compatibility writer resolves the
organization exclusively from the authenticated financial request scope.
"""

import hashlib
import os

from app.core.config import settings
from app.db.database import SessionLocal
from app.security.tenant_scope import current_organization_id
from app.services.secret_store import (
    get_secret_provider,
    put_tenant_secret,
    resolve_secret_reference,
    secret_reference,
)


def encrypt_value(value: str) -> str:
    """Store legacy ERP credentials in the centralized secret provider."""

    if not value:
        return ""

    organization_id = current_organization_id(required=settings.is_production)
    if not settings.is_production:
        provider = get_secret_provider()
        tenant_label = str(organization_id) if organization_id is not None else "test"
        name = (
            f"tenant-{tenant_label}-erp-test-"
            + hashlib.sha256(os.urandom(32)).hexdigest()[:20]
        )
        remote = provider.set_secret(
            name,
            value,
            tags={
                "purpose": "erp_credentials",
                "environment": settings.APP_ENV,
                "organization_id": tenant_label,
            },
        )
        return f"secretref://{provider.provider_name}/{remote.name}/{remote.version}"

    if organization_id is None:
        # ``required=True`` above already fails closed; the explicit branch
        # keeps type checkers and future refactors honest.
        raise RuntimeError("An authenticated tenant scope is required.")

    db = SessionLocal()
    try:
        binding = put_tenant_secret(
            db,
            organization_id=organization_id,
            actor_user_id=None,
            purpose="erp_credentials",
            value=value,
        )
        return secret_reference(binding)
    finally:
        db.close()


def decrypt_value(reference: str) -> str:
    """Resolve a versioned remote secret reference; ciphertext is not accepted."""

    if not reference:
        return ""
    if not reference.startswith("secretref://"):
        raise ValueError("Legacy encrypted values are no longer accepted.")
    try:
        return resolve_secret_reference(reference)
    except Exception as exc:
        raise ValueError("Secure secret reference could not be resolved.") from exc


def rotate_encryption_key(*_args: object, **_kwargs: object) -> str:
    raise RuntimeError(
        "Local encryption-key rotation was removed. Rotate the tenant secret through the centralized secret store."
    )
