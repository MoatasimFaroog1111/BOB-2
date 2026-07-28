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
from app.worker.tasks import _run_audited_task

pytestmark = pytest.mark.skipif(
    not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Real Redis and PostgreSQL are required for worker process tests",
)


def _create_organization(prefix: str) -> int:
    db = SessionLocal()
    try:
        organization = Organization(
            name=f"{prefix} {uuid.uuid4().hex[:10]}",
            legal_name=f"{prefix} Organization",
            country="SA",
            is_active=True,
        )
        db.add(organization)
        db.commit()
        db.refresh(organization)
        return int(organization.id)
    finally:
        db.close()


def _job_audit_events(organization_id: int, job_id: str) -> list[AuditLog]:
    db = SessionLocal()
    try:
        with tenant_scope(organization_id):
            return (
                db.query(AuditLog)
                .filter(
                    AuditLog.organization_id == organization_id,
                    AuditLog.entity_type == "background_job",
                    AuditLog.entity_id == job_id,
                )
                .order_by(AuditLog.sequence_number.asc())
                .all()
            )
    finally:
        db.close()


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

    organization_id = _create_organization("Worker Test")
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

    events = _job_audit_events(organization_id, job_id)
    assert [event.action for event in events] == [
        "worker_job_started",
        "worker_job_completed",
    ]
    assert all(event.details["kind"] == "worker_smoke_test" for event in events)
    assert all(event.event_hash and len(event.event_hash) == 64 for event in events)


def test_failed_task_records_started_and_failed_audit_events():
    organization_id = _create_organization("Worker Failure Test")
    job_id = f"worker-failure-{uuid.uuid4().hex}"

    async def failing_operation() -> dict:
        raise RuntimeError("intentional worker failure")

    async def execute_failure() -> None:
        with tenant_scope(organization_id):
            await _run_audited_task(
                {"job_id": job_id, "job_try": 2},
                organization_id=organization_id,
                kind="failure_probe",
                operation=failing_operation,
            )

    with pytest.raises(RuntimeError, match="intentional worker failure"):
        asyncio.run(execute_failure())

    events = _job_audit_events(organization_id, job_id)
    assert [event.action for event in events] == [
        "worker_job_started",
        "worker_job_failed",
    ]
    assert events[-1].details == {
        "job_id": job_id,
        "kind": "failure_probe",
        "job_try": 2,
        "error_code": "RuntimeError",
    }
    assert all(event.event_hash and len(event.event_hash) == 64 for event in events)
