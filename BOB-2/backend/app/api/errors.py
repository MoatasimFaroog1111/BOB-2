"""Stable, user-safe HTTP error contracts shared by API routers."""

import logging

from fastapi import HTTPException, status

logger = logging.getLogger("app.api")


def unexpected_operation_error(
    *,
    code: str,
    message: str,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
) -> HTTPException:
    """Log the active exception and return a disclosure-safe public contract."""
    logger.exception("API operation failed", extra={"public_error_code": code})
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def ai_provider_unavailable() -> HTTPException:
    """Return a provider-agnostic error without disclosing deployment configuration."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "ai_provider_unavailable",
            "message": "AI assistant is temporarily unavailable.",
        },
    )
