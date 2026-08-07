"""Tenant-scoped arq tasks with immutable audit events."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.db.database import SessionLocal
from app.models.core import AuditLog
from app.security.tenant_scope import tenant_scope
from app.services.job_runs import cleanup_job_uploads, store_job_result, update_job_run
from app.services.long_running_operations import (
    analyze_documents,
    chat_spreadsheet,
    match_documents,
    parse_bank_statement,
    reconcile_bank_statement,
)

logger = logging.getLogger(__name__)
TaskOperation = Callable[[], Awaitable[dict[str, Any]]]


def _audit_worker_event(*, organization_id: int, job_id: str, kind: str, action: str, job_try: int, error_code: str | None = None) -> None:
    db = SessionLocal()
    try:
        details: dict[str, Any] = {"job_id": job_id, "kind": kind, "job_try": job_try}
        if error_code:
            details["error_code"] = error_code[:100]
        db.add(AuditLog(organization_id=organization_id, user_id=None, action=action, entity_type="background_job", entity_id=job_id[:100], details=details))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _run_audited_task(ctx: dict[str, Any], *, organization_id: int, kind: str, operation: TaskOperation) -> dict[str, Any]:
    job_id = str(ctx.get("job_id") or "unknown")
    job_try = int(ctx.get("job_try") or 1)
    _audit_worker_event(organization_id=organization_id, job_id=job_id, kind=kind, action="worker_job_started", job_try=job_try)
    try:
        result = await operation()
    except BaseException as exc:
        _audit_worker_event(organization_id=organization_id, job_id=job_id, kind=kind, action="worker_job_failed", job_try=job_try, error_code=type(exc).__name__)
        raise
    _audit_worker_event(organization_id=organization_id, job_id=job_id, kind=kind, action="worker_job_completed", job_try=job_try)
    return result


async def _execute_managed_job(ctx: dict[str, Any], *, organization_id: int, job_id: str, kind: str, operation: TaskOperation) -> dict[str, Any]:
    update_job_run(organization_id=organization_id, job_id=job_id, status_value="running", progress=5)

    async def managed_operation() -> dict[str, Any]:
        try:
            result = await operation()
            store_job_result(organization_id=organization_id, job_id=job_id, result=result)
            update_job_run(organization_id=organization_id, job_id=job_id, status_value="completed", progress=100)
            return result
        except BaseException as exc:
            update_job_run(organization_id=organization_id, job_id=job_id, status_value="failed", progress=100, error_code=type(exc).__name__)
            raise

    return await _run_audited_task(ctx, organization_id=organization_id, kind=kind, operation=managed_operation)


def _final_attempt(ctx: dict[str, Any]) -> bool:
    return int(ctx.get("job_try") or 1) >= 3


async def _run_file_job(ctx: dict[str, Any], *, organization_id: int, job_id: str, kind: str, operation: TaskOperation) -> dict[str, Any]:
    try:
        result = await _execute_managed_job(ctx, organization_id=organization_id, job_id=job_id, kind=kind, operation=operation)
    except BaseException:
        if _final_attempt(ctx):
            cleanup_job_uploads(organization_id, job_id)
        raise
    cleanup_job_uploads(organization_id, job_id)
    return result


async def worker_smoke_test(ctx: dict[str, Any], organization_id: int) -> dict[str, Any]:
    with tenant_scope(organization_id):
        async def operation() -> dict[str, Any]:
            await asyncio.sleep(0)
            return {"status": "completed", "organization_id": organization_id, "job_id": str(ctx.get("job_id") or "unknown")}
        return await _run_audited_task(ctx, organization_id=organization_id, kind="worker_smoke_test", operation=operation)


async def process_documents_job(ctx: dict[str, Any], organization_id: int, job_id: str, files: list[dict[str, str]]) -> dict[str, Any]:
    with tenant_scope(organization_id):
        async def operation() -> dict[str, Any]:
            return await asyncio.to_thread(analyze_documents, files)
        return await _run_file_job(ctx, organization_id=organization_id, job_id=job_id, kind="document_ocr", operation=operation)


async def match_documents_job(ctx: dict[str, Any], organization_id: int, job_id: str, files: list[dict[str, str]]) -> dict[str, Any]:
    with tenant_scope(organization_id):
        async def operation() -> dict[str, Any]:
            return await asyncio.to_thread(match_documents, files)
        return await _run_file_job(ctx, organization_id=organization_id, job_id=job_id, kind="document_matching", operation=operation)


async def parse_bank_statement_job(ctx: dict[str, Any], organization_id: int, job_id: str, file_item: dict[str, str], date_from: str | None, date_to: str | None) -> dict[str, Any]:
    with tenant_scope(organization_id):
        async def operation() -> dict[str, Any]:
            return await asyncio.to_thread(parse_bank_statement, file_item, date_from=date_from, date_to=date_to)
        return await _run_file_job(ctx, organization_id=organization_id, job_id=job_id, kind="bank_statement_parse", operation=operation)


async def reconcile_bank_statement_job(ctx: dict[str, Any], organization_id: int, job_id: str, file_item: dict[str, str], date_from: str | None, date_to: str | None, company_id: int | None, bank_journal_id: int | None) -> dict[str, Any]:
    with tenant_scope(organization_id):
        async def operation() -> dict[str, Any]:
            return await asyncio.to_thread(reconcile_bank_statement, organization_id, file_item, date_from=date_from, date_to=date_to, company_id=company_id, bank_journal_id=bank_journal_id)
        return await _run_file_job(ctx, organization_id=organization_id, job_id=job_id, kind="bank_reconciliation", operation=operation)


async def chat_spreadsheet_job(ctx: dict[str, Any], organization_id: int, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with tenant_scope(organization_id):
        async def operation() -> dict[str, Any]:
            return await asyncio.to_thread(chat_spreadsheet, payload)
        return await _execute_managed_job(ctx, organization_id=organization_id, job_id=job_id, kind="spreadsheet_llm", operation=operation)
