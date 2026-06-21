"""Tests for configuration and settings."""

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
