import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.runtime_security import validate_runtime_security as validate_runtime_environment
from app.middleware.audit import AuditLogMiddleware
from app.middleware.request_size import RequestSizeLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.security.document_processing_guard import install_document_processing_guard
from app.security.file_validation import verify_malware_scanner_ready
from app.security.ocr_guard import install_ocr_guard
from app.services.readiness import readiness_snapshot
from app.services.telegram_runtime import (
    install_runtime_guard,
    start_telegram_bot,
    stop_telegram_bot,
)

configure_logging()
logger = logging.getLogger(__name__)

_RAILWAY_ENVIRONMENT_VARIABLES = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)

# Railway terminates TLS and performs host routing at its managed edge. Only
# controls genuinely supplied by that edge may be delegated. Redis, malware
# scanning, secret storage, database, ERP egress and every other application
# control stay fail-closed on Railway exactly as on every production runtime.
_RAILWAY_DELEGATED_SECURITY_ERRORS = {
    "TRUSTED_HOSTS is required",
    "TRUSTED_PROXY_IPS is required",
    "REQUIRE_HTTPS must be true",
    "FRONTEND_ORIGIN must use https",
}


def _is_railway_runtime() -> bool:
    """Return whether the process is running inside a Railway service."""
    return any(os.getenv(name, "").strip() for name in _RAILWAY_ENVIRONMENT_VARIABLES)


def _validate_startup_security() -> None:
    """Validate production settings while respecting Railway's managed edge.

    The ordinary production profile remains fully fail-closed. On Railway only
    controls supplied by the platform edge may be absent. Every application-level
    validation error still aborts startup.
    """
    if _is_railway_runtime() and not settings.is_production:
        raise ValueError(
            "Railway runtime requires APP_ENV=production; refusing to start "
            "with development security defaults."
        )

    try:
        validate_runtime_environment(settings)
    except ValueError as exc:
        if not _is_railway_runtime():
            raise

        prefix = "Unsafe production configuration: "
        message = str(exc)
        details = message.removeprefix(prefix)
        violations = [item.strip() for item in details.split(";") if item.strip()]
        unresolved = [
            violation
            for violation in violations
            if violation not in _RAILWAY_DELEGATED_SECURITY_ERRORS
        ]
        if unresolved:
            raise ValueError(prefix + "; ".join(unresolved)) from exc

        logger.warning(
            "Railway managed-edge startup accepted with delegated controls: %s",
            "; ".join(violations),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize bounded fail-closed production guards.

    Database migrations and baseline seeding run through Railway's pre-deploy
    command. The malware scanner check is the only bounded dependency probe here:
    production must prove that clean bytes pass and EICAR is detected before the
    API accepts traffic.
    """
    _validate_startup_security()
    if settings.is_production and settings.REQUIRE_MALWARE_SCAN:
        await asyncio.to_thread(verify_malware_scanner_ready)
    install_ocr_guard()
    install_document_processing_guard()
    install_runtime_guard()

    telegram_started = False
    if settings.TELEGRAM_BOT_ENABLED:
        try:
            telegram_started = start_telegram_bot()
        except Exception:
            logger.exception("Telegram bot startup failed safely")

    try:
        yield
    finally:
        if settings.TELEGRAM_BOT_ENABLED or telegram_started:
            try:
                stop_telegram_bot(reason="application_shutdown")
            except Exception:
                logger.exception("Telegram bot shutdown failed")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.2.0",
    description="GuardianAI Accountant & Auditor Enterprise Backend Core",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)

# This middleware is intentionally installed first so the subsequently installed
# audit/security/CORS middleware still wraps and annotates 413 responses.
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_bytes=settings.MAX_REQUEST_SIZE_MB * 1024 * 1024,
    max_upload_files=settings.MAX_UPLOAD_FILES,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditLogMiddleware)

app.add_middleware(
    CORSMiddleware,
    # التعديل تم هنا بدمج رابط الفرونت إند الخاص بك مع قائمة الإعدادات الأساسية
    allow_origins=settings.cors_origin_list + ["https://bob-front-end-production.up.railway.app"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
    ],
    expose_headers=["X-Request-ID"],
    max_age=600,
)

if settings.is_production:
    # Railway's healthcheck uses healthcheck.railway.app and the platform owns
    # host routing. Outside Railway, explicit production host validation remains.
    if settings.trusted_host_list and not _is_railway_runtime():
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_host_list,
        )

    # Railway terminates public TLS before forwarding traffic to the container.
    # App-level redirect middleware would redirect its HTTP health probe.
    if settings.REQUIRE_HTTPS and not _is_railway_runtime():
        app.add_middleware(HTTPSRedirectMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception at %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please try again later.",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )


@app.get("/health")
def health_check():
    """Minimal unauthenticated liveness endpoint."""
    from datetime import datetime, timezone

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def readiness_check():
    """Dependency-aware readiness without exposing credentials or error details."""
    snapshot = readiness_snapshot()
    return JSONResponse(
        status_code=200 if snapshot["status"] == "ready" else 503,
        content=snapshot,
    )


app.include_router(api_router, prefix="/api/v1")
