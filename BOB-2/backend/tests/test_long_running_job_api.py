"""HTTP contracts for queued OCR, reconciliation, and LLM work."""

from __future__ import annotations

import io
import time

from fastapi.routing import APIRoute

from app.api.v1.long_running_jobs import _REPLACED_PATHS
from app.main import app
from app.models.job_run import JobRun


def test_active_heavy_routes_use_queued_replacements():
    active = {
        route.path: route.endpoint.__module__
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/erp/")
    }
    for relative_path in _REPLACED_PATHS:
        absolute_path = f"/api/v1/erp{relative_path}"
        assert active[absolute_path] == "app.api.v1.long_running_jobs"


def test_large_upload_returns_queued_response_under_one_second(
    client,
    auth_headers,
    db,
    monkeypatch,
):
    captured: dict[str, object] = {}

    async def fake_persist(files, *, organization_id: int, job_id: str):
        captured["file_count"] = len(files)
        return [{"path": "/tmp/queued-large.csv", "filename": "large.csv"}]

    async def fake_enqueue(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.api.v1.long_running_jobs.persist_validated_uploads",
        fake_persist,
    )
    monkeypatch.setattr(
        "app.api.v1.long_running_jobs.enqueue_background_job",
        fake_enqueue,
    )

    payload = b"Date,Description,Amount\n" + b"2026-01-01,Transfer,1.00\n" * 75_000
    started = time.perf_counter()
    response = client.post(
        "/api/v1/erp/bank-statement-parse",
        files={"statement": ("large.csv", io.BytesIO(payload), "text/csv")},
        headers=auth_headers,
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 202, response.text
    assert elapsed < 1.0
    body = response.json()
    assert body["status"] == "queued"
    assert body["kind"] == "bank_statement_parse"
    assert body["progress"] == 0
    assert captured["function_name"] == "parse_bank_statement_job"
    assert captured["organization_id"] == 1
    assert captured["job_id"] == body["job_id"]

    run = db.query(JobRun).filter(JobRun.job_id == body["job_id"]).one()
    assert run.organization_id == 1
    assert run.status == "queued"

    status_response = client.get(
        f"/api/v1/jobs/{body['job_id']}",
        headers=auth_headers,
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"
    assert status_response.json()["result"] is None


def test_job_status_cannot_cross_tenant_boundary(client, auth_headers, db):
    from app.models.core import Organization

    db.add(Organization(id=2, name="Other Org", country="SA", is_active=True))
    db.add(
        JobRun(
            job_id="other-tenant-job",
            organization_id=2,
            kind="document_ocr",
            status="completed",
            progress=100,
        )
    )
    db.commit()

    response = client.get(
        "/api/v1/jobs/other-tenant-job",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_sync_rollback_flag_invokes_legacy_handler(
    client,
    auth_headers,
    monkeypatch,
):
    async def fake_legacy(statement, date_from, date_to, company_id):
        return {"status": "success", "mode": "synchronous"}

    monkeypatch.setenv("ASYNC_LONG_RUNNING_JOBS_ENABLED", "false")
    monkeypatch.setattr(
        "app.api.v1.long_running_jobs.legacy_parse_bank_statement",
        fake_legacy,
    )
    response = client.post(
        "/api/v1/erp/bank-statement-parse",
        files={
            "statement": (
                "statement.csv",
                io.BytesIO(b"Date,Description,Amount\n2026-01-01,Test,1.00\n"),
                "text/csv",
            )
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success", "mode": "synchronous"}
