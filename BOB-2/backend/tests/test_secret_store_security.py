from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.core import AuditLog, Organization, User
from app.models.tenant_secret import TenantSecretBinding, TenantSecretVersion
from app.security.auth import hash_password
from app.services.secret_store import (
    SecretNotConfigured,
    get_tenant_secret,
    put_tenant_secret,
    reset_secret_provider_for_tests,
    resolve_secret_reference,
    revoke_tenant_secret,
    secret_reference,
)


@pytest.fixture(autouse=True)
def memory_secret_provider(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_STORE_PROVIDER", "memory")
    reset_secret_provider_for_tests()
    yield
    reset_secret_provider_for_tests()


def _seed(db, org_id: int, user_id: int):
    db.add(Organization(id=org_id, name=f"Org {org_id}", country="SA", is_active=True))
    db.add(
        User(
            id=user_id,
            organization_id=org_id,
            email=f"owner{user_id}@example.test",
            full_name=f"Owner {user_id}",
            role="owner",
            hashed_password=hash_password("Test@Pass1234!"),
            is_active=True,
        )
    )
    db.commit()


def test_secret_values_never_enter_database_and_rotation_is_versioned(db):
    _seed(db, 11, 101)
    first_value = "111111:telegram-first-value"
    second_value = "222222:telegram-rotated-value"

    first = put_tenant_secret(
        db,
        organization_id=11,
        actor_user_id=101,
        purpose="telegram_bot_token",
        value=first_value,
    )
    assert first.status == "active"
    assert first_value not in json.dumps(first.__dict__, default=str)
    assert get_tenant_secret(db, organization_id=11, purpose="telegram_bot_token") == first_value

    second = put_tenant_secret(
        db,
        organization_id=11,
        actor_user_id=101,
        purpose="telegram_bot_token",
        value=second_value,
    )
    assert second.id == first.id
    assert second.current_version != first.current_version or second.last_rotated_at >= first.last_rotated_at
    assert get_tenant_secret(db, organization_id=11, purpose="telegram_bot_token") == second_value

    versions = (
        db.query(TenantSecretVersion)
        .filter(TenantSecretVersion.binding_id == second.id)
        .order_by(TenantSecretVersion.id)
        .all()
    )
    assert len(versions) == 2
    assert [row.status for row in versions] == ["superseded", "active"]
    database_dump = json.dumps(
        [row.__dict__ for row in db.query(TenantSecretBinding).all()]
        + [row.__dict__ for row in versions]
        + [row.details for row in db.query(AuditLog).all()],
        default=str,
    )
    assert first_value not in database_dump
    assert second_value not in database_dump


def test_secret_bindings_are_tenant_isolated(db):
    _seed(db, 21, 201)
    _seed(db, 22, 202)
    put_tenant_secret(
        db,
        organization_id=21,
        actor_user_id=201,
        purpose="external_llm_api_key",
        value="tenant-one-external-key-value",
    )
    put_tenant_secret(
        db,
        organization_id=22,
        actor_user_id=202,
        purpose="external_llm_api_key",
        value="tenant-two-external-key-value",
    )
    assert get_tenant_secret(db, organization_id=21, purpose="external_llm_api_key") == "tenant-one-external-key-value"
    assert get_tenant_secret(db, organization_id=22, purpose="external_llm_api_key") == "tenant-two-external-key-value"
    assert db.query(TenantSecretBinding).count() == 2


def test_revoke_disables_current_version_and_fails_closed(db):
    _seed(db, 31, 301)
    put_tenant_secret(
        db,
        organization_id=31,
        actor_user_id=301,
        purpose="erp_credentials",
        value='{"username":"user","password":"secret-value"}',
    )
    revoked = revoke_tenant_secret(
        db,
        organization_id=31,
        actor_user_id=301,
        purpose="erp_credentials",
    )
    assert revoked is not None
    assert revoked.status == "revoked"
    with pytest.raises(SecretNotConfigured):
        get_tenant_secret(db, organization_id=31, purpose="erp_credentials")


def test_versioned_reference_resolves_without_storing_ciphertext(db):
    _seed(db, 41, 401)
    binding = put_tenant_secret(
        db,
        organization_id=41,
        actor_user_id=401,
        purpose="erp_credentials",
        value='{"username":"odoo","password":"remote-only"}',
    )
    reference = secret_reference(binding)
    assert reference.startswith("secretref://memory/")
    assert resolve_secret_reference(reference) == '{"username":"odoo","password":"remote-only"}'
    assert "remote-only" not in reference


def test_telegram_admin_api_never_returns_token(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_STORE_PROVIDER", "memory")
    reset_secret_provider_for_tests()
    token = "1234567890:telegram-token-that-must-never-return"
    response = client.put(
        "/api/v1/communication-tools/telegram-token",
        json={"token": token},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert token not in response.text
    assert "secret_name" not in response.text
    assert response.json()["configured"] is True

    status_response = client.get(
        "/api/v1/communication-tools/telegram-token/status",
        headers=auth_headers,
    )
    assert status_response.status_code == 200
    assert token not in status_response.text
    assert status_response.json()["storage"] == "central_secret_store"

    delete_response = client.delete(
        "/api/v1/communication-tools/telegram-token",
        headers=auth_headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["configured"] is False


def test_no_local_secret_files_or_fernet_key_generation_remain():
    root = Path(__file__).resolve().parents[1] / "app"
    telegram_source = (root / "services" / "telegram_bot.py").read_text(encoding="utf-8")
    communication_source = (root / "api" / "v1" / "communication_tools.py").read_text(encoding="utf-8")
    encryption_source = (root / "security" / "encryption.py").read_text(encoding="utf-8")
    combined = "\n".join((telegram_source, communication_source, encryption_source))
    assert "Fernet.generate_key" not in combined
    assert "communication_tools.key" not in combined
    assert "telegram_config.json" not in combined
    assert "encrypted_token" not in combined
    assert "PBKDF2HMAC" not in combined
    assert "SECRET_KEY.encode" not in encryption_source
