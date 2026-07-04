"""
Security headers middleware to add common security headers to all responses.
These headers help protect against various web attacks like XSS, clickjacking, etc.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings


def _build_csp() -> str:
    """Build Content-Security-Policy allowing cross-origin API calls from known frontend origins."""
    extra_origins = " ".join(o for o in settings.cors_origin_list if o != "'self'")
    connect_src = f"'self' {extra_origins}".strip() if extra_origins else "'self' *"
    return (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        f"connect-src {connect_src}; "
        "frame-ancestors 'none'; "
        "base-uri 'self';"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all HTTP responses."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent clickjacking attacks
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Enable XSS protection in browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy to limit information leakage
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content-Security-Policy — connect-src includes all configured CORS origins
        # so the frontend can call the backend API even when on a different subdomain.
        response.headers["Content-Security-Policy"] = _build_csp()

        # Permissions Policy to limit browser features
        permissions = (
            "accelerometer=(), "
            "camera=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(), "
            "payment=(), "
            "usb=()"
        )
        response.headers["Permissions-Policy"] = permissions

        # HSTS — enabled automatically when REQUIRE_HTTPS is true
        if settings.REQUIRE_HTTPS:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Hide server information
        response.headers["Server"] = "GuardianAI"

        return response
