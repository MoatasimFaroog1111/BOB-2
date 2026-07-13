"""Regression tests for centralized financial route authorization."""

from app.models.core import User
from app.security.auth import hash_password


def _viewer_headers(client, db) -> dict[str, str]:
    password = "Viewer@Test1234!"
    db.add(
        User(
            organization_id=1,
            email="viewer@guardian.test",
            full_name="Read Only Viewer",
            role="viewer",
            hashed_password=hash_password(password),
            is_active=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@guardian.test", "password": password},
        headers={"User-Agent": "pytest-viewer-client"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_role_metadata_requires_authentication(client):
    response = client.get("/api/v1/auth/roles")
    assert response.status_code == 401


def test_owner_can_read_role_metadata(client, auth_headers):
    response = client.get("/api/v1/auth/roles", headers=auth_headers)
    assert response.status_code == 200
    assert "owner" in response.json()["roles"]


def test_viewer_cannot_read_erp_connection_settings(client, db, seeded_user):
    headers = _viewer_headers(client, db)
    response = client.get("/api/v1/erp/connection", headers=headers)
    assert response.status_code == 403
    assert "manage_settings" in response.json()["detail"]


def test_viewer_can_use_read_only_financial_route(client, db, seeded_user):
    headers = _viewer_headers(client, db)
    response = client.get("/api/v1/erp/companies", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_viewer_cannot_trigger_financial_ai_mutation(client, db, seeded_user):
    headers = _viewer_headers(client, db)
    response = client.post(
        "/api/v1/agents/run-accounting-workflow",
        headers=headers,
        json={
            "text": "Tax invoice INV-1 subtotal 1000 VAT 150 total 1150 supplier Guardian",
            "source_type": "invoice",
            "organization_id": 1,
            "language": "auto",
        },
    )
    assert response.status_code == 403
    assert "create_entries" in response.json()["detail"]


def test_viewer_cannot_post_or_reverse_odoo_entries(client, db, seeded_user):
    headers = _viewer_headers(client, db)
    response = client.post(
        "/api/v1/erp/journal-entry/TEST-2026-0001/post",
        headers=headers,
    )
    assert response.status_code == 403
    assert "post_odoo_entries" in response.json()["detail"]
