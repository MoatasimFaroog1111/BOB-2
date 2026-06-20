"""Tests for authentication endpoints and security utilities."""

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


# ── Password hashing ────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_and_verify(self):
        raw = "Str0ng!Pass"
        hashed = hash_password(raw)
        assert verify_password(raw, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("CorrectPass1!")
        assert not verify_password("WrongPass1!", hashed)


# ── Password strength ───────────────────────────────────────

class TestPasswordStrength:
    def test_valid_password(self):
        ok, msg = validate_password_strength("Valid@Pass1")
        assert ok
        assert msg == ""

    def test_too_short(self):
        ok, _ = validate_password_strength("Ab1!")
        assert not ok

    def test_no_uppercase(self):
        ok, _ = validate_password_strength("nouppercase1!")
        assert not ok

    def test_no_digit(self):
        ok, _ = validate_password_strength("NoDigitsHere!")
        assert not ok

    def test_common_password(self):
        ok, _ = validate_password_strength("password")
        assert not ok


# ── JWT tokens ───────────────────────────────────────────────

class TestJWT:
    def test_access_token_roundtrip(self):
        token = create_access_token(subject="user@test.com", role="owner")
        payload = decode_access_token(token)
        assert payload["sub"] == "user@test.com"
        assert payload["role"] == "owner"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        token = create_refresh_token(subject="user@test.com")
        payload = decode_refresh_token(token)
        assert payload["sub"] == "user@test.com"
        assert payload["type"] == "refresh"

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


# ── RBAC ─────────────────────────────────────────────────────

class TestRBAC:
    def test_owner_has_wildcard(self):
        assert role_has_permission("owner", "anything")

    def test_viewer_limited(self):
        assert role_has_permission("viewer", "view_dashboard")
        assert not role_has_permission("viewer", "manage_users")

    def test_invalid_role(self):
        assert not role_has_permission("nonexistent", "view_dashboard")

    def test_all_roles_exist(self):
        assert len(UserRole) == 6


# ── Login endpoint ───────────────────────────────────────────

class TestLoginEndpoint:
    def test_login_success(self, client, seeded_user):
        resp = client.post("/api/v1/auth/login", json={
            "email": seeded_user["email"],
            "password": seeded_user["password"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["role"] == "owner"

    def test_login_wrong_password(self, client, seeded_user):
        resp = client.post("/api/v1/auth/login", json={
            "email": seeded_user["email"],
            "password": "WrongPass!1",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "email": "nobody@test.com",
            "password": "Some@Pass1",
        })
        assert resp.status_code == 401

    def test_refresh_token(self, client, seeded_user):
        login = client.post("/api/v1/auth/login", json={
            "email": seeded_user["email"],
            "password": seeded_user["password"],
        })
        refresh_token = login.json()["refresh_token"]
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()


# ── Health & system ──────────────────────────────────────────

class TestHealthAndSystem:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_system_status(self, client):
        resp = client.get("/api/v1/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["security_features"]["rate_limiting"] is True

    def test_roles_list(self, client):
        resp = client.get("/api/v1/auth/roles")
        assert resp.status_code == 200
        roles = resp.json()["roles"]
        assert "owner" in roles
        assert len(roles) == 6
