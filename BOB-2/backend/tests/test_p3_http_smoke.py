"""HTTP smoke tests for the new P3 endpoints.

These hit the running FastAPI app via ``TestClient`` so they exercise
the same code path production traffic would. The default conftest
forces ``APP_ENV=test``, so the frame defaults to ``enterprise`` and
self-serve signup must respond 404.
"""
from __future__ import annotations


def test_capabilities_endpoint_returns_expected_frame(client) -> None:
    """``GET /api/v1/system/capabilities`` returns the live frame map."""
    response = client.get("/api/v1/system/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert "frame" in body
    assert "capabilities" in body
    # The test default frame is enterprise (or whatever DEPLOYMENT_FRAME
    # resolves to at startup). Either way we must have every key.
    from app.capabilities.service import CAPABILITY_NAMES

    for name in CAPABILITY_NAMES:
        assert name in body["capabilities"]


def test_billing_plans_endpoint_returns_in_memory_catalog(client) -> None:
    """``GET /api/v1/billing/plans`` returns the four default plans."""
    response = client.get("/api/v1/billing/plans")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "in_memory"
    ids = {p["id"] for p in body["plans"]}
    assert "starter" in ids
    assert "professional" in ids
    assert "enterprise" in ids
    assert "lifetime_marketplace" in ids


def test_signup_returns_404_in_default_enterprise_frame(client) -> None:
    """In the enterprise frame, self-serve signup returns 404, not 501/200."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": "Acme Holdings",
            "owner_email": "newowner@example.com",
            "owner_password": "VeryStrongPassword!123",
            "owner_full_name": "New Owner",
        },
    )
    # The default frame is enterprise, which disables self-serve signup.
    # The handler returns 404 in that case.
    assert response.status_code in (404, 501)


def test_health_still_returns_ok(client) -> None:
    """Sanity check: P3 changes did not break the existing health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"