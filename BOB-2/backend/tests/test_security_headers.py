"""Tests for security headers middleware."""

from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.main import app


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        resp = client.get("/health")
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        # Modern browsers ignore the legacy XSS auditor; disabling it avoids
        # auditor-induced vulnerabilities while CSP remains authoritative.
        assert resp.headers["X-XSS-Protection"] == "0"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        csp = resp.headers["Content-Security-Policy"]
        assert "unsafe-inline" not in csp
        assert "unsafe-eval" not in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "Permissions-Policy" in resp.headers
        assert resp.headers["Server"] == "GuardianAI"

    def test_no_hsts_in_dev(self, client):
        resp = client.get("/health")
        assert "Strict-Transport-Security" not in resp.headers


class TestCORS:
    def test_cors_origins_come_only_from_runtime_settings(self):
        cors = next(
            middleware
            for middleware in app.user_middleware
            if middleware.cls is CORSMiddleware
        )
        assert cors.kwargs["allow_origins"] == settings.cors_origin_list

    def test_cors_allows_configured_origin(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
