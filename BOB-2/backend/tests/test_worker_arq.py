"""End-to-end arq worker regression using real Redis and PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid

import pytest
from arq import create_pool
from arq.jobs import Job

from app.db.database import SessionLocal
from app.models.core import AuditLog, Organization
from app.security.tenant_scope import tenant_scope
from app.worker.settings import (
    WORKER_QUEUE_NAME,
    WorkerSettings,
    _worker_redis_settings,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Real Redis and PostgreSQL are required for worker process tests",
)


async def _enqueue_smoke_job(organization_id: int, job_id: str) -> None:
    redis = await create_pool(
        _worker_redis_settings(),
        default_queue_name=WORKER_QUEUE_NAME,
    )
    try:
        await redis.flushdb()
        job = await redis.enqueue_job(
            "worker_smoke_test",
            organization_id,
            _job_id=job_id,
        )
        assert job is not None
    finally:
        await redis.aclose()


async def _read_job_result(job_id: str) -> dict:
    redis = await create_pool(
        _worker_redis_settings(),
        default_queue_name=WORKER_QUEUE_NAME,
    )
    try:
        job = Job(job_id=job_id, redis=redis, _queue_name=WORKER_QUEUE_NAME)
        return await job.result(timeout=10)
    finally:
        await redis.aclose()


def test_worker_executes_job_outside_web_process_and_audits_lifecycle():
    assert WorkerSettings.max_jobs == 4
    assert WorkerSettings.job_timeout == 300
    assert WorkerSettings.keep_result == 3600
    assert WorkerSettings.max_tries == 3
    assert WorkerSettings.retry_jobs is True

    db = SessionLocal()
    organization = Organization(
        name=f"Worker Test {uuid.uuid4().hex[:10]}",
        legal_name="Worker Test Organization",
        country="SA",
        is_active=True,
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    organization_id = int(organization.id)
    db.close()

    job_id = f"worker-smoke-{uuid.uuid4().hex}"
    asyncio.run(_enqueue_smoke_job(organization_id, job_id))

    arq_binary = shutil.which("arq")
    assert arq_binary, "arq CLI was not installed"
    process = subprocess.run(
        [
            arq_binary,
            "app.worker.settings.WorkerSettings",
            "--burst",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ.copy(),
    )
    assert process.returncode == 0, process.stdout + process.stderr

    result = asyncio.run(_read_job_result(job_id))
    assert result == {
        "status": "completed",
        "organization_id": organization_id,
        "job_id": job_id,
    }

    db = SessionLocal()
    try:
        with tenant_scope(organization_id):
            events = (
                db.query(AuditLog)
                .filter(
                    AuditLog.organization_id == organization_id,
                    AuditLog.entity_type == "background_job",
                    AuditLog.entity_id == job_id,
                )
                .order_by(AuditLog.sequence_number.asc())
                .all()
            )
        assert [event.action for event in events] == [
            "worker_job_started",
            "worker_job_completed",
        ]
        assert all(event.details["kind"] == "worker_smoke_test" for event in events)
        assert all(event.event_hash and len(event.event_hash) == 64 for event in events)
    finally:
        db.close()
