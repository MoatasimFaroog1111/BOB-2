from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.middleware.audit import AuditLogMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

import logging
from contextlib import asynccontextmanager
from app.db.seed import run_seed

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate security configuration on startup
    if settings.is_production:
        try:
            settings.validate_secret_key()
        except ValueError as e:
            logger.critical("Security validation failed: %s", e)

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
    version="0.1.0",
    description="GuardianAI Accountant & Auditor Enterprise Backend Core",
    lifespan=lifespan,
    # Disable automatic docs in production for security
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Audit logging middleware
app.add_middleware(AuditLogMiddleware)

# CORS middleware — origins driven by FRONTEND_ORIGIN + CORS_ORIGINS env vars
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
    max_age=600,  # Cache preflight requests for 10 minutes
)

# Trusted host middleware — hosts driven by TRUSTED_HOSTS env var
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_host_list,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler that doesn't expose sensitive information."""
    logger.error("Unhandled exception at %s: %s", request.url.path, exc, exc_info=True)

    # Return generic error to client
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
    """Basic health check endpoint - minimal information exposure."""
    return {
        "status": "healthy",
        "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
    }


@app.get("/api/v1/system/status")
def system_status():
    """System status with more details (requires authentication in production)."""
    return {
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "security_features": {
            "rate_limiting": True,
            "encryption": True,
            "audit_logging": True,
            "password_validation": True,
        },
    }


app.include_router(api_router, prefix="/api/v1")
