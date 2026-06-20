"""Tests for security headers middleware."""


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        resp = client.get("/health")
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in resp.headers
        assert "Permissions-Policy" in resp.headers
        assert resp.headers["Server"] == "GuardianAI"

    def test_no_hsts_in_dev(self, client):
        resp = client.get("/health")
        assert "Strict-Transport-Security" not in resp.headers


class TestCORS:
    def test_cors_allows_configured_origin(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
