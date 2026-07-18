from __future__ import annotations

import base64
import os

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, settings
from app.models.encrypted_secret import EncryptedSecretVersion
from app.services import encrypted_secret_provider as provider_module
from app.services.encrypted_secret_provider import EncryptedDatabaseSecretProvider
from app.services.secret_provider_types import SecretStoreError


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _bind_provider_to_fixture(db, monkeypatch) -> None:
    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db.get_bind(),
    )
    monkeypatch.setattr(provider_module, "SessionLocal", factory)


def test_production_accepts_encrypted_db_with_exact_32_byte_key():
    candidate = Settings(
        _env_file=None,
        APP_ENV="production",
        DATABASE_URL="postgresql://guardian:strong-password@db:5432/guardianai",
        REDIS_URL="redis://:strong-password@redis:6379/0",
        SECRET_KEY="x" * 64,
        FRONTEND_ORIGIN="https://app.example.test",
        TRUSTED_HOSTS="app.example.test",
        TRUSTED_PROXY_IPS="127.0.0.1/32",
        REQUIRE_HTTPS=True,
        REQUIRE_MALWARE_SCAN=True,
        CLAMAV_HOST="clamav",
        ERP_OUTBOUND_ALLOWED_HOSTS="odoo.example.test",
        SECRET_STORE_PROVIDER="encrypted_db",
        SECRET_STORE_ENCRYPTION_KEY=_key(),
    )
    candidate.validate_runtime_security()


@pytest.mark.parametrize(
    "key",
    ["", "not-base64", base64.b64encode(b"short").decode("ascii")],
)
def test_production_rejects_invalid_encrypted_db_key(key):
    candidate = Settings(
        _env_file=None,
        APP_ENV="production",
        DATABASE_URL="postgresql://guardian:strong-password@db:5432/guardianai",
        REDIS_URL="redis://:strong-password@redis:6379/0",
        SECRET_KEY="x" * 64,
        FRONTEND_ORIGIN="https://app.example.test",
        TRUSTED_HOSTS="app.example.test",
        TRUSTED_PROXY_IPS="127.0.0.1/32",
        REQUIRE_HTTPS=True,
        REQUIRE_MALWARE_SCAN=True,
        CLAMAV_HOST="clamav",
        ERP_OUTBOUND_ALLOWED_HOSTS="odoo.example.test",
        SECRET_STORE_PROVIDER="encrypted_db",
        SECRET_STORE_ENCRYPTION_KEY=key,
    )
    with pytest.raises(ValueError, match="SECRET_STORE_ENCRYPTION_KEY"):
        candidate.validate_runtime_security()


def test_encrypt_decrypt_wrong_key_and_tenant_metadata(db, monkeypatch):
    _bind_provider_to_fixture(db, monkeypatch)
    first_key = _key()
    monkeypatch.setattr(settings, "SECRET_STORE_ENCRYPTION_KEY", first_key)
    provider = EncryptedDatabaseSecretProvider()

    remote = provider.set_secret(
        "org-91-erp-credential",
        "extremely-sensitive-value",
        tags={"organization_id": "91", "purpose": "erp_credentials"},
    )
    row = db.query(EncryptedSecretVersion).one()
    assert b"extremely-sensitive-value" not in row.ciphertext
    assert row.organization_id == 91
    assert row.purpose == "erp_credentials"
    assert provider.get_secret(remote.name, remote.version) == "extremely-sensitive-value"

    monkeypatch.setattr(settings, "SECRET_STORE_ENCRYPTION_KEY", _key())
    wrong_provider = EncryptedDatabaseSecretProvider()
    with pytest.raises(SecretStoreError, match="secure secret store") as exc:
        wrong_provider.get_secret(remote.name, remote.version)
    assert exc.value.reason == "encrypted_db_authentication_failed"


def test_authenticated_metadata_tampering_is_rejected(db, monkeypatch):
    _bind_provider_to_fixture(db, monkeypatch)
    monkeypatch.setattr(settings, "SECRET_STORE_ENCRYPTION_KEY", _key())
    provider = EncryptedDatabaseSecretProvider()
    remote = provider.set_secret(
        "org-92-token",
        "tenant-secret",
        tags={"organization_id": "92", "purpose": "telegram_bot_token"},
    )
    row = db.query(EncryptedSecretVersion).one()
    row.organization_id = 93
    db.commit()

    with pytest.raises(SecretStoreError) as exc:
        provider.get_secret(remote.name, remote.version)
    assert exc.value.reason == "encrypted_db_authentication_failed"
