"""Tenant-scoped in-memory cache for frequently fetched Odoo data."""

import threading
import time
from typing import Any, Dict, List, Optional

from app.security.tenant_scope import current_organization_id

TTL_SECONDS = 600

_lock = threading.Lock()
_store: Dict[str, Dict[str, Any]] = {}


def _cache_key(provider_url: str, db_name: str, kind: str) -> str:
    organization_id = current_organization_id(required=True)
    return f"org:{organization_id}|{provider_url}|{db_name}|{kind}"


def get_cached(provider_url: str, db_name: str, kind: str) -> Optional[List]:
    key = _cache_key(provider_url, db_name, kind)
    with _lock:
        entry = _store.get(key)
        if entry and (time.monotonic() - entry["ts"]) < TTL_SECONDS:
            return entry["data"]
    return None


def set_cached(provider_url: str, db_name: str, kind: str, data: List) -> None:
    key = _cache_key(provider_url, db_name, kind)
    with _lock:
        _store[key] = {"data": data, "ts": time.monotonic()}


def invalidate(provider_url: str = "", db_name: str = "") -> None:
    """Drop only the authenticated tenant's cache entries."""

    organization_id = current_organization_id(required=True)
    tenant_prefix = f"org:{organization_id}|"
    with _lock:
        if not provider_url:
            keys = [key for key in _store if key.startswith(tenant_prefix)]
        else:
            prefix = f"{tenant_prefix}{provider_url}|{db_name}|"
            keys = [key for key in _store if key.startswith(prefix)]
        for key in keys:
            del _store[key]
