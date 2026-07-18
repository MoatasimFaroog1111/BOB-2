from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.encrypted_secret import EncryptedSecretVersion
from app.security.audit_chain import utc_naive
from app.services.secret_provider_types import RemoteSecretVersion, SecretStoreError

_SECRET_NAME_PATTERN = re.compile(r"^[0-9A-Za-z-]{1,127}$")
_KEY_VERSION = 1
_NONCE_BYTES = 12


@dataclass(frozen=True, slots=True)
class _SecretContext:
    organization_id: int
    purpose: str


def _decode_key() -> bytes:
    raw = settings.SECRET_STORE_ENCRYPTION_KEY.strip()
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretStoreError("encrypted_db_key_invalid") from exc
    if len(key) != 32:
        raise SecretStoreError("encrypted_db_key_invalid")
    return key


def _context(tags: dict[str, str]) -> _SecretContext:
    try:
        organization_id = int(tags["organization_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SecretStoreError("encrypted_db_tenant_context_invalid") from exc
    purpose = tags.get("purpose", "").strip().lower()
    if organization_id <= 0 or not purpose:
        raise SecretStoreError("encrypted_db_tenant_context_invalid")
    return _SecretContext(organization_id=organization_id, purpose=purpose)


def _aad(
    *,
    name: str,
    version: str,
    organization_id: int,
    purpose: str,
    key_version: int,
) -> bytes:
    payload = {
        "provider": "encrypted_db",
        "name": name,
        "version": version,
        "organization_id": int(organization_id),
        "purpose": purpose,
        "key_version": int(key_version),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class EncryptedDatabaseSecretProvider:
    provider_name = "encrypted_db"

    def __init__(self) -> None:
        self._key = _decode_key()
        self._aesgcm = AESGCM(self._key)

    def set_secret(
        self,
        name: str,
        value: str,
        *,
        tags: dict[str, str],
    ) -> RemoteSecretVersion:
        if not _SECRET_NAME_PATTERN.fullmatch(name):
            raise SecretStoreError("secret_name_invalid")
        if not value:
            raise SecretStoreError("secret_value_invalid")
        context = _context(tags)
        version = os.urandom(24).hex()
        nonce = os.urandom(_NONCE_BYTES)
        aad = _aad(
            name=name,
            version=version,
            organization_id=context.organization_id,
            purpose=context.purpose,
            key_version=_KEY_VERSION,
        )
        ciphertext = self._aesgcm.encrypt(nonce, value.encode("utf-8"), aad)

        db = SessionLocal()
        try:
            db.add(
                EncryptedSecretVersion(
                    secret_name=name,
                    version=version,
                    organization_id=context.organization_id,
                    purpose=context.purpose,
                    nonce=nonce,
                    ciphertext=ciphertext,
                    key_version=_KEY_VERSION,
                    authenticated_tags={
                        "organization_id": str(context.organization_id),
                        "purpose": context.purpose,
                    },
                    status="active",
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return RemoteSecretVersion(name=name, version=version)

    def get_secret(self, name: str, version: str) -> str:
        if not _SECRET_NAME_PATTERN.fullmatch(name) or not version:
            raise SecretStoreError("secret_reference_invalid")
        db = SessionLocal()
        try:
            row = (
                db.query(EncryptedSecretVersion)
                .filter(
                    EncryptedSecretVersion.secret_name == name,
                    EncryptedSecretVersion.version == version,
                    EncryptedSecretVersion.status == "active",
                )
                .first()
            )
            if row is None:
                raise SecretStoreError("encrypted_db_secret_version_missing")
            aad = _aad(
                name=row.secret_name,
                version=row.version,
                organization_id=row.organization_id,
                purpose=row.purpose,
                key_version=row.key_version,
            )
            try:
                plaintext = self._aesgcm.decrypt(row.nonce, row.ciphertext, aad)
            except InvalidTag as exc:
                raise SecretStoreError("encrypted_db_authentication_failed") from exc
            try:
                return plaintext.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SecretStoreError("encrypted_db_plaintext_invalid") from exc
        finally:
            db.close()

    def disable_secret(self, name: str, version: str) -> None:
        if not _SECRET_NAME_PATTERN.fullmatch(name) or not version:
            raise SecretStoreError("secret_reference_invalid")
        db = SessionLocal()
        try:
            row = (
                db.query(EncryptedSecretVersion)
                .filter(
                    EncryptedSecretVersion.secret_name == name,
                    EncryptedSecretVersion.version == version,
                )
                .with_for_update()
                .first()
            )
            if row is not None:
                row.status = "disabled"
                row.disabled_at = utc_naive()
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
