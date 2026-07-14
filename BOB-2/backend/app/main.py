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
from app.db.seed import run_seed
from app.middleware.audit import AuditLogMiddleware
from app.middleware.request_size import RequestSizeLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.security.document_processing_guard import install_document_processing_guard
from app.security.ocr_guard import install_ocr_guard
from app.services.telegram_runtime import (
    install_runtime_guard,
    start_telegram_bot,
    stop_telegram_bot,
)

configure_logging()
logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Run Alembic migrations to ensure the database schema is up to date."""
    try:
        from alembic import command
        from alembic.config import Config

        alembic_ini = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
        alembic_cfg = Config(alembic_ini)
        alembic_cfg.set_main_option(
            "script_location",
            os.path.join(os.path.dirname(__file__), "..", "migrations"),
        )
        alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations applied successfully.")
    except Exception as exc:
        logger.error("Failed to run migrations: %s", exc)
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_runtime_security()
    install_ocr_guard()
    install_document_processing_guard()
    _run_migrations()
    run_seed()

    # Install the compatibility patch before any legacy ERP endpoint can import
    # the Telegram start/stop functions. All runtime entry points are therefore
    # governed by the same fail-closed policy.
    install_runtime_guard()
    try:
        start_telegram_bot()
    except Exception:
        logger.exception("Telegram bot startup failed safely")

    try:
        yield
    finally:
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
    allow_origins=settings.cors_origin_list,
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
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_host_list,
    )
    if settings.REQUIRE_HTTPS:
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


app.include_router(api_router, prefix="/api/v1")
