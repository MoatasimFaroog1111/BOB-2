"""Queue adapter for tenant-scoped arq jobs."""

from __future__ import annotations

from typing import Any

from arq import create_pool
from fastapi import HTTPException, status

from app.services.job_runs import update_job_run
from app.worker.settings import WORKER_QUEUE_NAME, _worker_redis_settings


async def enqueue_background_job(
    *,
    function_name: str,
    organization_id: int,
    job_id: str,
    args: tuple[Any, ...] = (),
) -> None:
    redis = None
    try:
        redis = await create_pool(
            _worker_redis_settings(),
            default_queue_name=WORKER_QUEUE_NAME,
        )
        queued = await redis.enqueue_job(
            function_name,
            organization_id,
            job_id,
            *args,
            _job_id=job_id,
        )
        if queued is None:
            raise RuntimeError("duplicate_or_rejected_job_id")
    except Exception as exc:
        update_job_run(
            organization_id=organization_id,
            job_id=job_id,
            status_value="failed",
            progress=0,
            error_code="queue_unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing service is temporarily unavailable.",
            headers={"Retry-After": "60"},
        ) from exc
    finally:
        if redis is not None:
            await redis.aclose()
