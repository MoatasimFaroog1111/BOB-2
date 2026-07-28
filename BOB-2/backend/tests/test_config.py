"""Tests for configuration and settings."""

import pytest
from fastapi import HTTPException

from app.core.config import Settings, generate_secret_key


class TestConfig:
    def test_secret_key_generation(self):
        key = generate_secret_key()
        assert len(key) >= 32

    def test_cors_origin_list_includes_frontend(self):
        from app.core.config import settings
        origins = settings.cors_origin_list
        assert settings.FRONTEND_ORIGIN in origins

    def test_non_production_includes_localhost(self):
        from app.core.config import settings
        origins = settings.cors_origin_list
        assert "http://localhost:3000" in origins

    def test_allowed_extensions_list(self):
        from app.core.config import settings
        exts = settings.allowed_upload_extensions_list
        assert ".pdf" in exts
        assert ".png" in exts

    def test_is_not_production_by_default(self):
        from app.core.config import settings
        assert not settings.is_production

    def test_shared_redis_key_is_environment_and_tenant_scoped(self, monkeypatch):
        from app.core.config import settings
        from app.core.redis_client import build_redis_key

        monkeypatch.setattr(settings, "APP_ENV", "Production")
        key = build_redis_key(
            "Bank Reconciliation",
            organization_id=42,
            parts=("jobs", "abc:123"),
        )

        assert key == (
            "guardian:production:bank-reconciliation:"
            "org:42:jobs:abc%3A123"
        )

    def test_shared_redis_key_rejects_invalid_organization(self):
        from app.core.redis_client import build_redis_key

        with pytest.raises(ValueError, match="organization_id"):
            build_redis_key("auth", organization_id=-1)

    def test_production_without_redis_fails_closed(self, monkeypatch):
        from app.core.config import settings
        from app.core.redis_client import get_redis_client

        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "REDIS_URL", "")

        with pytest.raises(HTTPException) as exc_info:
            get_redis_client()

        assert exc_info.value.status_code == 503


class TestRateLimiter:
    def test_record_and_check(self):
        from app.security.rate_limiter import LoginRateLimiter
        limiter = LoginRateLimiter()
        limiter.record_attempt("test-ip", success=False)
        locked, _ = limiter.is_locked_out("test-ip")
        assert not locked

    def test_lockout_after_max_attempts(self):
        from app.security.rate_limiter import LoginRateLimiter
        limiter = LoginRateLimiter()
        for _ in range(10):
            limiter.record_attempt("brute", success=False)
        locked, remaining = limiter.is_locked_out("brute")
        assert locked
        assert remaining > 0

    def test_success_clears_attempts(self):
        from app.security.rate_limiter import LoginRateLimiter
        limiter = LoginRateLimiter()
        for _ in range(3):
            limiter.record_attempt("user1", success=False)
        limiter.record_attempt("user1", success=True)
        locked, _ = limiter.is_locked_out("user1")
        assert not locked
