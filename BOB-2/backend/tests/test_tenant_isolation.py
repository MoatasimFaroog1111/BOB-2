"""Tenant isolation regression tests."""

from app.models.core import Organization, User
from app.security.auth import hash_password


def _organization_two_headers(client, db) -> dict[str, str]:
    db.add(
        Organization(
            id=2,
            name="Tenant Two",
            legal_name="Tenant Two LLC",
            country="SA",
            is_active=True,
        )
    )
    password = "Tenant2@Test1234!"
    db.add(
        User(
            organization_id=2,
            email="owner@tenant-two.test",
            full_name="Tenant Two Owner",
            role="owner",
            hashed_password=hash_password(password),
            is_active=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@tenant-two.test", "password": password},
        headers={"User-Agent": "pytest-tenant-two"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_other_tenant_can_enter_legacy_routes_without_seeing_tenant_one_data(client, db):
    headers = _organization_two_headers(client, db)
    response = client.get("/api/v1/erp/companies", headers=headers)
    assert response.status_code == 200, response.text
    # No ERP connection exists for tenant two. The route must not fall back to
    # an organization-one connection or leak its company list.
    assert response.json() == []


def test_other_tenant_can_use_tenant_isolated_journal_api(client, db):
    headers = _organization_two_headers(client, db)
    create_response = client.post(
        "/api/v1/journal/entries",
        headers=headers,
        json={
            "date": "2026-07-13",
            "reference": "TENANT2/2026/0001",
            "memo": "Tenant-isolated test entry",
            "status": "draft",
            "lines": [
                {"account": "1000", "debit": 100, "credit": 0, "description": "Cash"},
                {"account": "3000", "debit": 0, "credit": 100, "description": "Capital"},
            ],
        },
    )
    assert create_response.status_code == 201, create_response.text

    list_response = client.get("/api/v1/journal/entries", headers=headers)
    assert list_response.status_code == 200
    assert [entry["reference"] for entry in list_response.json()] == ["TENANT2/2026/0001"]
