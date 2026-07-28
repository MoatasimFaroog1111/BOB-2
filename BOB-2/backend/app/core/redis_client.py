"""Shared Redis client, fail-closed handling, and tenant-scoped key construction."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, status
from redis import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

REDIS_CONNECT_TIMEOUT_SECONDS = 2
REDIS_READ_TIMEOUT_SECONDS = 2
REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30

_client_lock = threading.RLock()
_client: Redis | None = None
_pool: ConnectionPool | None = None
_client_url = ""
_NAMESPACE_PATTERN = re.compile(r"[^a-z0-9_-]+")


def _namespace_segment(value: str, *, label: str) -> str:
    normalized = _NAMESPACE_PATTERN.sub("-", str(value).strip().lower()).strip("-")
    if not normalized:
        raise ValueError(f"Redis {label} must contain at least one safe character")
    return normalized


def _key_part(value: Any) -> str:
    if value is None:
        raise ValueError("Redis key parts cannot be None")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("Redis key parts cannot be empty")
    return quote(normalized, safe="-_.|/")


def build_redis_key(
    domain: str,
    *,
    organization_id: int,
    parts: Iterable[Any] = (),
) -> str:
    """Build a namespaced Redis key with an explicit organization scope.

    ``organization_id=0`` is reserved for controls that run before a tenant is
    authenticated, such as global login abuse protection. Tenant-owned data must
    use its positive organization identifier.
    """

    if isinstance(organization_id, bool) or not isinstance(organization_id, int):
        raise ValueError("organization_id must be an integer")
    if organization_id < 0:
        raise ValueError("organization_id cannot be negative")

    environment = _namespace_segment(settings.APP_ENV, label="environment")
    normalized_domain = _namespace_segment(domain, label="domain")
    suffix = [f"org:{organization_id}", *(_key_part(part) for part in parts)]
    return f"guardian:{environment}:{normalized_domain}:" + ":".join(suffix)


def handle_redis_unavailable(
    exc: Exception,
    *,
    component: str,
    public_detail: str = "Shared state service temporarily unavailable.",
) -> None:
    """Log a Redis failure and fail closed in production.

    Non-production callers may continue to their explicitly local fallback after
    this function returns. Production callers always receive HTTP 503.
    """

    logger.error("Redis unavailable for %s: %s", component, exc)
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=public_detail,
            headers={"Retry-After": "60"},
        ) from exc


def _clear_client_locked() -> None:
    global _client, _pool, _client_url

    if _pool is not None:
        try:
            _pool.disconnect()
        except Exception:
            logger.warning("Unable to disconnect the previous Redis pool cleanly")
    _client = None
    _pool = None
    _client_url = ""


def get_redis_client() -> Redis | None:
    """Return the process-wide Redis client and connection pool.

    Redis is mandatory in production. Local development and tests may receive
    ``None`` and use a process-local fallback owned by the caller.
    """

    global _client, _pool, _client_url

    configured_url = settings.REDIS_URL.strip()
    if not configured_url:
        with _client_lock:
            if _client is not None or _pool is not None:
                _clear_client_locked()
        missing = RuntimeError("REDIS_URL is not configured")
        handle_redis_unavailable(missing, component="Redis configuration")
        return None

    with _client_lock:
        if _client is not None and _client_url == configured_url:
            return _client

        if _client is not None or _pool is not None:
            _clear_client_locked()

        try:
            pool = ConnectionPool.from_url(
                configured_url,
                decode_responses=True,
                socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=REDIS_READ_TIMEOUT_SECONDS,
                health_check_interval=REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
            )
            client = Redis(connection_pool=pool)
        except Exception as exc:
            handle_redis_unavailable(exc, component="Redis client initialization")
            return None

        _pool = pool
        _client = client
        _client_url = configured_url
        return _client


__all__ = [
    "RedisError",
    "build_redis_key",
    "get_redis_client",
    "handle_redis_unavailable",
]
