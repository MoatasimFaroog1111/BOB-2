"""arq worker configuration shared by local, CI, and Railway processes."""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.worker import func

from app.core.config import settings
from app.core.redis_client import build_redis_key
from app.worker.tasks import worker_smoke_test

WORKER_QUEUE_NAME = build_redis_key(
    "jobs",
    organization_id=0,
    parts=("queue",),
)
WORKER_HEALTH_CHECK_KEY = build_redis_key(
    "jobs",
    organization_id=0,
    parts=("worker-health",),
)


def _worker_redis_settings() -> RedisSettings:
    redis_url = settings.REDIS_URL.strip()
    if not redis_url:
        if settings.is_production:
            raise RuntimeError("REDIS_URL is required for the production worker")
        return RedisSettings(
            conn_timeout=2,
            conn_retries=3,
            conn_retry_delay=1,
            max_connections=20,
            retry_on_timeout=True,
        )

    configured = RedisSettings.from_dsn(redis_url)
    configured.conn_timeout = 2
    configured.conn_retries = 5
    configured.conn_retry_delay = 1
    configured.max_connections = 20
    configured.retry_on_timeout = True
    return configured


class WorkerSettings:
    functions = [
        func(
            worker_smoke_test,
            name="worker_smoke_test",
            timeout=60,
            keep_result=300,
            max_tries=3,
        )
    ]
    redis_settings = _worker_redis_settings()
    queue_name = WORKER_QUEUE_NAME
    max_jobs = 4
    job_timeout = 300
    keep_result = 3600
    max_tries = 3
    retry_jobs = True
    health_check_interval = 30
    health_check_key = WORKER_HEALTH_CHECK_KEY
    job_completion_wait = 30
