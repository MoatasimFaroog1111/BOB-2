"""Stage 11 regressions for request-bound financial tenant isolation."""

from __future__ import annotations

import json
from pathlib import Path

from app.erp import discovery, odoo_cache
from app.models.core import ERPConnection, Organization, User
from app.security.auth import hash_password
from app.security.tenant_scope import current_organization_id, tenant_scope
from app.services.secret_store import get_secret_provider


def _secret_reference(name: str, username: str) -> str:
    provider = get_secret_provider()
    stored = provider.set_secret(
        name,
        json.dumps({"username": username, "password": f"{username}-password"}),
        tags={"purpose": "erp_credentials", "test": "tenant-isolation"},
    )
    return f"secretref://{provider.provider_name}/{stored.name}/{stored.version}"


def _second_tenant(db) -> dict[str, object]:
    organization = Organization(
        id=2,
        name="Second Tenant",
        legal_name="Second Tenant LLC",
        country="SA",
        is_active=True,
    )
    password = "Second@Tenant123!"
    user = User(
        id=2,
        organization_id=2,
        email="second-tenant@guardian-ai.com",
        full_name="Second Tenant Owner",
        role="owner",
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add_all([organization, user])
    db.commit()
    return {"organization": organization, "user": user, "password": password}


def _login(client, email: str, password: str, user_agent: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"User-Agent": user_agent},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "User-Agent": user_agent,
    }


def test_legacy_erp_connection_read_is_rewritten_to_authenticated_tenant(
    client,
    seeded_user,
    db,
):
    second = _second_tenant(db)
    first_connection = ERPConnection(
        organization_id=1,
        provider="odoo",
        base_url="https://tenant-one.example.com",
        database_name="tenant_one",
        auth_type="password",
        encrypted_secret_ref=_secret_reference("tenant-one-read", "tenant-one-user"),
        is_active=True,
    )
    second_connection = ERPConnection(
        organization_id=2,
        provider="odoo",
        base_url="https://tenant-two.example.com",
        database_name="tenant_two",
        auth_type="password",
        encrypted_secret_ref=_secret_reference("tenant-two-read", "tenant-two-user"),
        is_active=True,
    )
    db.add_all([first_connection, second_connection])
    db.commit()

    second_headers = _login(
        client,
        second["user"].email,
        second["password"],
        "tenant-two-read-test",
    )
    response = client.get("/api/v1/erp/connection", headers=second_headers)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == second_connection.id
    assert response.json()["url"] == "https://tenant-two.example.com"
    assert response.json()["username"] == "tenant-two-user"

    first_headers = _login(
        client,
        seeded_user["email"],
        seeded_user["password"],
        "tenant-one-read-test",
    )
    first_response = client.get("/api/v1/erp/connection", headers=first_headers)
    assert first_response.status_code == 200, first_response.text
    assert first_response.json()["id"] == first_connection.id
    assert first_response.json()["url"] == "https://tenant-one.example.com"


def test_legacy_connection_save_updates_only_current_tenant(
    client,
    seeded_user,
    db,
    monkeypatch,
):
    second = _second_tenant(db)
    first_connection = ERPConnection(
        organization_id=1,
        provider="odoo",
        base_url="https://tenant-one.example.com",
        database_name="tenant_one",
        auth_type="password",
        encrypted_secret_ref=_secret_reference("tenant-one-save", "tenant-one-user"),
        is_active=True,
    )
    second_connection = ERPConnection(
        organization_id=2,
        provider="odoo",
        base_url="https://tenant-two-old.example.com",
        database_name="tenant_two_old",
        auth_type="password",
        encrypted_secret_ref=_secret_reference("tenant-two-save", "tenant-two-user"),
        is_active=True,
    )
    db.add_all([first_connection, second_connection])
    db.commit()

    class FakeERP:
        def test_connection(self):
            return {"connected": True}

    monkeypatch.setattr("app.api.v1.erp.get_erp_provider", lambda **_kwargs: FakeERP())
    headers = _login(
        client,
        second["user"].email,
        second["password"],
        "tenant-two-save-test",
    )
    response = client.post(
        "/api/v1/erp/connection",
        headers=headers,
        json={
            "provider": "odoo",
            "url": "https://tenant-two-new.example.com",
            "db": "tenant_two_new",
            "username": "tenant-two-new-user",
            "password": "tenant-two-new-password",
        },
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    unchanged_first = db.query(ERPConnection).filter(ERPConnection.id == first_connection.id).one()
    updated_second = db.query(ERPConnection).filter(ERPConnection.id == second_connection.id).one()
    assert unchanged_first.base_url == "https://tenant-one.example.com"
    assert unchanged_first.database_name == "tenant_one"
    assert updated_second.organization_id == 2
    assert updated_second.base_url == "https://tenant-two-new.example.com"
    assert updated_second.database_name == "tenant_two_new"


def test_hardcoded_legacy_predicate_and_insert_are_tenant_rewritten(db):
    _second_tenant(db)
    db.add_all(
        [
            ERPConnection(
                organization_id=1,
                provider="odoo",
                base_url="https://one.example.com",
                database_name="one",
                auth_type="password",
                encrypted_secret_ref="secretref://memory/one/1",
                is_active=True,
            ),
            ERPConnection(
                organization_id=2,
                provider="odoo",
                base_url="https://two.example.com",
                database_name="two",
                auth_type="password",
                encrypted_secret_ref="secretref://memory/two/1",
                is_active=True,
            ),
        ]
    )
    db.commit()

    with tenant_scope(2):
        selected = (
            db.query(ERPConnection)
            .filter(ERPConnection.organization_id == 1)
            .order_by(ERPConnection.id.asc())
            .all()
        )
        assert selected
        assert {row.organization_id for row in selected} == {2}

        legacy_insert = ERPConnection(
            organization_id=1,
            provider="odoo",
            base_url="https://two-created.example.com",
            database_name="two_created",
            auth_type="password",
            encrypted_secret_ref="secretref://memory/two-created/1",
            is_active=True,
        )
        db.add(legacy_insert)
        db.commit()
        db.refresh(legacy_insert)
        assert legacy_insert.organization_id == 2

    assert current_organization_id(required=False) is None


def test_odoo_cache_is_namespaced_by_tenant():
    with tenant_scope(1):
        odoo_cache.set_cached("https://shared.example.com", "shared", "accounts", ["one"])
    with tenant_scope(2):
        assert odoo_cache.get_cached("https://shared.example.com", "shared", "accounts") is None
        odoo_cache.set_cached("https://shared.example.com", "shared", "accounts", ["two"])
        assert odoo_cache.get_cached("https://shared.example.com", "shared", "accounts") == ["two"]
    with tenant_scope(1):
        assert odoo_cache.get_cached("https://shared.example.com", "shared", "accounts") == ["one"]
        odoo_cache.invalidate("https://shared.example.com", "shared")
        assert odoo_cache.get_cached("https://shared.example.com", "shared", "accounts") is None
    with tenant_scope(2):
        assert odoo_cache.get_cached("https://shared.example.com", "shared", "accounts") == ["two"]
        odoo_cache.invalidate()


def test_discovery_files_are_separate_and_identity_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "STORAGE_DIR", Path(tmp_path))

    class FakeProvider:
        url = "https://shared.example.com"
        db = "shared"

        def discover_accounts(self):
            return [{"id": 1}]

        def discover_journals(self):
            return []

        def discover_taxes(self):
            return []

        def discover_partners(self):
            return []

        def discover_analytic_accounts(self):
            return []

        def discover_products(self):
            return []

        def discover_employees(self):
            return []

        def get_company_info(self):
            return {"companies": [{"id": 10, "name": "Shared"}]}

    with tenant_scope(1):
        discovery.run_discovery_orchestrator(FakeProvider())
        tenant_one = discovery.load_financial_kb()
    with tenant_scope(2):
        discovery.run_discovery_orchestrator(FakeProvider())
        tenant_two = discovery.load_financial_kb()

    assert tenant_one["metadata"]["organization_id"] == 1
    assert tenant_two["metadata"]["organization_id"] == 2
    assert (tmp_path / "organization_1.json").is_file()
    assert (tmp_path / "organization_2.json").is_file()

    # A copied file with mismatched embedded identity is rejected.
    (tmp_path / "organization_2.json").write_text(
        json.dumps(tenant_one),
        encoding="utf-8",
    )
    with tenant_scope(2):
        assert discovery.load_financial_kb() is None
