"""Tenant-scoped Redis cache for frequently fetched Odoo data."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from app.core.redis_client import (
    RedisError,
    build_redis_key,
    get_redis_client,
    handle_redis_unavailable,
)
from app.security.tenant_scope import current_organization_id

logger = logging.getLogger(__name__)

TTL_SECONDS = 600
SCAN_COUNT = 100


def _legacy_cache_key(
    organization_id: int,
    provider_url: str,
    db_name: str,
    kind: str,
) -> str:
    """Preserve the original cache key shape inside the Redis namespace."""

    return f"org:{organization_id}|{provider_url}|{db_name}|{kind}"


def _cache_key(provider_url: str, db_name: str, kind: str) -> str:
    organization_id = current_organization_id(required=True)
    namespace = build_redis_key(
        "odoo-cache",
        organization_id=organization_id,
    )
    legacy_key = _legacy_cache_key(
        organization_id,
        provider_url,
        db_name,
        kind,
    )
    return f"{namespace}:{legacy_key}"


def _scan_prefix(provider_url: str = "", db_name: str = "") -> str:
    organization_id = current_organization_id(required=True)
    namespace = build_redis_key(
        "odoo-cache",
        organization_id=organization_id,
    )
    tenant_prefix = f"{namespace}:org:{organization_id}|"
    if not provider_url:
        return tenant_prefix
    return f"{tenant_prefix}{provider_url}|{db_name}|"


def _escape_scan_literal(value: str) -> str:
    """Escape Redis glob metacharacters before adding the trailing wildcard."""

    escaped = value.replace("\\", "\\\\")
    for character in ("*", "?", "[", "]"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _redis_unavailable(exc: Exception) -> None:
    handle_redis_unavailable(
        exc,
        component="Odoo cache",
        public_detail="ERP cache service temporarily unavailable.",
    )


def get_cached(provider_url: str, db_name: str, kind: str) -> Optional[List]:
    key = _cache_key(provider_url, db_name, kind)
    client = get_redis_client()
    if client is None:
        return None

    try:
        raw_value = client.get(key)
    except RedisError as exc:
        _redis_unavailable(exc)
        return None

    if raw_value is None:
        return None

    try:
        value = json.loads(raw_value)
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed Odoo cache payload")
        return None

    if not isinstance(value, list):
        logger.warning("Ignoring non-list Odoo cache payload")
        return None
    return value


def set_cached(provider_url: str, db_name: str, kind: str, data: List) -> None:
    key = _cache_key(provider_url, db_name, kind)
    client = get_redis_client()
    if client is None:
        return

    try:
        payload = json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        logger.warning("Skipping non-serializable Odoo cache payload")
        return

    try:
        client.set(key, payload, ex=TTL_SECONDS)
    except RedisError as exc:
        _redis_unavailable(exc)


def invalidate(provider_url: str = "", db_name: str = "") -> None:
    """Drop only the authenticated tenant's cache entries using Redis SCAN."""

    prefix = _scan_prefix(provider_url, db_name)
    client = get_redis_client()
    if client is None:
        return

    pattern = f"{_escape_scan_literal(prefix)}*"
    cursor = 0
    try:
        while True:
            cursor, keys = client.scan(
                cursor=cursor,
                match=pattern,
                count=SCAN_COUNT,
            )
            if keys:
                client.delete(*keys)
            if int(cursor) == 0:
                break
    except RedisError as exc:
        _redis_unavailable(exc)
