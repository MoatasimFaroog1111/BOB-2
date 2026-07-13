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
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.security.ocr_guard import install_ocr_guard

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
    _run_migrations()
    run_seed()
    try:
        from app.services.telegram_bot import start_telegram_bot

        start_telegram_bot()
    except Exception as start_err:
        logger.warning("Failed to start Telegram bot: %s", start_err)
    yield
    try:
        from app.services.telegram_bot import stop_telegram_bot

        stop_telegram_bot()
    except Exception as stop_err:
        logger.warning("Failed to stop Telegram bot: %s", stop_err)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.2.0",
    description="GuardianAI Accountant & Auditor Enterprise Backend Core",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
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
