"""In-memory cache for frequently fetched Odoo data.

Caches partners, accounts, reconcile models, and journals so that
repeated document-processing calls don't re-fetch the same data from
Odoo on every request. The cache expires after ``TTL_SECONDS`` (default
600 s / 10 min).
"""

import threading
import time
from typing import Any, Dict, List, Optional

TTL_SECONDS = 600  # 10 minutes

_lock = threading.Lock()
_store: Dict[str, Dict[str, Any]] = {}


def _cache_key(provider_url: str, db_name: str, kind: str) -> str:
    return f"{provider_url}|{db_name}|{kind}"


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
    """Drop cache entries. If no args, clear everything."""
    with _lock:
        if not provider_url:
            _store.clear()
            return
        prefix = f"{provider_url}|{db_name}|"
        keys = [k for k in _store if k.startswith(prefix)]
        for k in keys:
            del _store[k]
