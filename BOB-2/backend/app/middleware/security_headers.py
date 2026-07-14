"""Security headers applied to every API response."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings


def _build_csp() -> str:
    """Build a strict CSP without unsafe inline/eval script execution."""
    configured_origins = " ".join(settings.cors_origin_list)
    connect_src = f"'self' {configured_origins}".strip()
    return (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        f"connect-src {connect_src}; "
        "object-src 'none'; "
        "frame-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "worker-src 'self' blob:; "
        "upgrade-insecure-requests"
        if settings.REQUIRE_HTTPS
        else (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; font-src 'self'; "
            f"connect-src {connect_src}; object-src 'none'; frame-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
            "worker-src 'self' blob:"
        )
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # The legacy browser XSS auditor is disabled; CSP is the authoritative control.
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = _build_csp()
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        if settings.REQUIRE_HTTPS:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        response.headers["Server"] = "GuardianAI"
        return response
