from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.db.database import engine


def _database_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _redis_ready() -> bool:
    try:
        client = get_redis_client()
        if client is None:
            return not settings.is_production
        return bool(client.ping())
    except Exception:
        return False


def _storage_ready() -> bool:
    storage = Path(settings.STORAGE_DIR)
    try:
        storage.mkdir(parents=True, exist_ok=True)
        descriptor, path = tempfile.mkstemp(prefix=".readiness-", dir=storage)
        try:
            os.write(descriptor, b"ok")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            Path(path).unlink(missing_ok=True)
        return True
    except Exception:
        return False


def readiness_snapshot() -> dict[str, object]:
    components = {
        "database": _database_ready(),
        "redis": _redis_ready(),
        "storage": _storage_ready(),
    }
    return {
        "status": "ready" if all(components.values()) else "not_ready",
        "components": components,
    }
