"""Real worker completion test for T5 long-running jobs."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from arq import create_pool

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.core import AuditLog, Organization
from app.models.job_run import JobRun
from app.security.tenant_scope import tenant_scope
from app.services.job_runs import create_job_run, load_job_result
from app.worker.settings import WORKER_QUEUE_NAME, _worker_redis_settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("REDIS_URL")
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Real Redis and PostgreSQL are required for worker process tests",
)


async def _enqueue_parse_job(
    organization_id: int,
    job_id: str,
    file_item: dict[str, str],
) -> None:
    redis = await create_pool(
        _worker_redis_settings(),
        default_queue_name=WORKER_QUEUE_NAME,
    )
    try:
        await redis.flushdb()
        job = await redis.enqueue_job(
            "parse_bank_statement_job",
            organization_id,
            job_id,
            file_item,
            None,
            None,
            _job_id=job_id,
        )
        assert job is not None
    finally:
        await redis.aclose()


def test_bank_statement_job_reaches_completed_in_external_worker():
    db = SessionLocal()
    try:
        organization = Organization(
            name=f"T5 Worker {uuid.uuid4().hex[:10]}",
            legal_name="T5 Worker Test",
            country="SA",
            is_active=True,
        )
        db.add(organization)
        db.commit()
        db.refresh(organization)
        organization_id = int(organization.id)

        job_id = f"t5-parse-{uuid.uuid4().hex}"
        with tenant_scope(organization_id):
            create_job_run(
                db,
                organization_id=organization_id,
                kind="bank_statement_parse",
                job_id=job_id,
            )
    finally:
        db.close()

    upload_dir = settings.storage_path / "job_uploads" / str(organization_id) / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    statement_path = upload_dir / "001-statement.csv"
    statement_path.write_text(
        "Date,Description,Amount\n"
        "2026-01-05,ATM Withdrawal,-500.00\n"
        "2026-01-06,Salary,8000.00\n",
        encoding="utf-8",
    )
    file_item = {"path": str(statement_path), "filename": "statement.csv"}
    asyncio.run(_enqueue_parse_job(organization_id, job_id, file_item))

    arq_binary = shutil.which("arq")
    assert arq_binary
    process = subprocess.run(
        [arq_binary, "app.worker.settings.WorkerSettings", "--burst"],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env=os.environ.copy(),
    )
    assert process.returncode == 0, process.stdout + process.stderr

    db = SessionLocal()
    try:
        with tenant_scope(organization_id):
            run = db.query(JobRun).filter(JobRun.job_id == job_id).one()
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
        assert run.status == "completed"
        assert run.progress == 100
        assert run.error_code is None
        assert run.finished_at is not None
        assert [event.action for event in events] == [
            "worker_job_started",
            "worker_job_completed",
        ]
    finally:
        db.close()

    result = load_job_result(organization_id=organization_id, job_id=job_id)
    assert result is not None
    assert result["status"] == "success"
    assert result["statement_count"] == 2
    assert result["statement_total"] == 7500.0
    assert not upload_dir.exists()
