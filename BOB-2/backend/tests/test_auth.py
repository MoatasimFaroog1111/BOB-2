"""Tests for authentication endpoints and security utilities."""

from app.models.core import AuthSession
from app.security.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.security.roles import UserRole, role_has_permission


class TestPasswordHashing:
    def test_hash_and_verify(self):
        raw = "Str0ng!Password"
        hashed = hash_password(raw)
        assert verify_password(raw, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("CorrectPass1!")
        assert not verify_password("WrongPass1!", hashed)


class TestPasswordStrength:
    def test_valid_password(self):
        ok, msg = validate_password_strength("Valid@Password1")
        assert ok
        assert msg == ""

    def test_too_short(self):
        ok, _ = validate_password_strength("Ab1!")
        assert not ok

    def test_no_uppercase(self):
        ok, _ = validate_password_strength("nouppercase1!long")
        assert not ok

    def test_no_digit(self):
        ok, _ = validate_password_strength("NoDigitsHere!")
        assert not ok

    def test_published_seed_password_is_rejected(self):
        ok, _ = validate_password_strength("Owner@Seed#2026!")
        assert not ok


class TestJWT:
    def test_access_token_roundtrip(self):
        token = create_access_token(subject="user@test.com", role="owner")
        payload = decode_access_token(token)
        assert payload["sub"] == "user@test.com"
        assert payload["role"] == "owner"
        assert payload["type"] == "access"
        assert payload["jti"]

    def test_refresh_token_roundtrip(self):
        token = create_refresh_token(subject="user@test.com")
        payload = decode_refresh_token(token)
        assert payload["sub"] == "user@test.com"
        assert payload["type"] == "refresh"
        assert payload["jti"]

    def test_access_token_rejects_refresh(self):
        token = create_refresh_token(subject="user@test.com")
        try:
            decode_access_token(token)
            assert False, "Should have raised"
        except Exception:
            pass

    def test_refresh_token_rejects_access(self):
        token = create_access_token(subject="user@test.com", role="owner")
        try:
            decode_refresh_token(token)
            assert False, "Should have raised"
        except Exception:
            pass


class TestRBAC:
    def test_owner_has_wildcard(self):
        assert role_has_permission("owner", "anything")

    def test_viewer_limited(self):
        assert role_has_permission("viewer", "view_dashboard")
        assert role_has_permission("viewer", "view_financials")
        assert not role_has_permission("viewer", "manage_users")

    def test_accountant_cannot_post_odoo_entries(self):
        assert role_has_permission("accountant", "create_entries")
        assert not role_has_permission("accountant", "post_odoo_entries")

    def test_required_finance_roles_exist(self):
        roles = {role.value for role in UserRole}
        assert {"viewer", "accountant", "reviewer", "cfo", "finance_manager", "admin"}.issubset(roles)


class TestLoginEndpoint:
    def _login(self, client, seeded_user):
        return client.post(
            "/api/v1/auth/login",
            json={
                "email": seeded_user["email"],
                "password": seeded_user["password"],
            },
        )

    def test_login_success_creates_server_session(self, client, seeded_user, db):
        response = self._login(client, seeded_user)
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["role"] == "owner"
        assert db.query(AuthSession).count() == 1

    def test_login_wrong_password(self, client, seeded_user):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": seeded_user["email"], "password": "WrongPass!1"},
        )
        assert response.status_code == 401

    def test_refresh_rotates_token_and_detects_reuse(self, client, seeded_user):
        login = self._login(client, seeded_user)
        old_refresh = login.json()["refresh_token"]

        rotated = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert rotated.status_code == 200
        assert rotated.json()["refresh_token"] != old_refresh

        reuse = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert reuse.status_code == 401

        # Reuse revokes the token family, including the newly rotated token.
        new_token_after_reuse = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": rotated.json()["refresh_token"]},
        )
        assert new_token_after_reuse.status_code == 401

    def test_logout_revokes_access_token(self, client, seeded_user):
        login = self._login(client, seeded_user).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 200

        status_response = client.get("/api/v1/system/status", headers=headers)
        assert status_response.status_code == 401


class TestProtectedFinanceEndpoints:
    def test_financial_router_without_token_returns_401(self, client):
        response = client.get("/api/v1/erp/connection")
        assert response.status_code == 401

    def test_journal_without_token_returns_401(self, client):
        response = client.get("/api/v1/journal/entries")
        assert response.status_code == 401


class TestHealthAndSystem:
    def test_health_is_public_and_minimal(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        assert "environment" not in response.json()

    def test_system_status_requires_authentication(self, client):
        response = client.get("/api/v1/system/status")
        assert response.status_code == 401

    def test_system_status_for_owner(self, client, seeded_user):
        login = client.post(
            "/api/v1/auth/login",
            json={"email": seeded_user["email"], "password": seeded_user["password"]},
        ).json()
        response = client.get(
            "/api/v1/system/status",
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "running"
