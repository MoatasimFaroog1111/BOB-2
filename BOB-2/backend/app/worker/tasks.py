"""Tenant-scoped arq tasks with immutable audit events."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.db.database import SessionLocal
from app.models.core import AuditLog
from app.security.tenant_scope import tenant_scope

logger = logging.getLogger(__name__)

TaskOperation = Callable[[], Awaitable[dict[str, Any]]]


def _audit_worker_event(
    *,
    organization_id: int,
    job_id: str,
    kind: str,
    action: str,
    job_try: int,
    error_code: str | None = None,
) -> None:
    """Append one worker lifecycle event through the canonical AuditLog chain."""

    db = SessionLocal()
    try:
        details: dict[str, Any] = {
            "job_id": job_id,
            "kind": kind,
            "job_try": job_try,
        }
        if error_code:
            details["error_code"] = error_code[:100]
        db.add(
            AuditLog(
                organization_id=organization_id,
                user_id=None,
                action=action,
                entity_type="background_job",
                entity_id=job_id[:100],
                details=details,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _run_audited_task(
    ctx: dict[str, Any],
    *,
    organization_id: int,
    kind: str,
    operation: TaskOperation,
) -> dict[str, Any]:
    job_id = str(ctx.get("job_id") or "unknown")
    job_try = int(ctx.get("job_try") or 1)
    _audit_worker_event(
        organization_id=organization_id,
        job_id=job_id,
        kind=kind,
        action="worker_job_started",
        job_try=job_try,
    )
    try:
        result = await operation()
    except BaseException as exc:
        _audit_worker_event(
            organization_id=organization_id,
            job_id=job_id,
            kind=kind,
            action="worker_job_failed",
            job_try=job_try,
            error_code=type(exc).__name__,
        )
        raise

    _audit_worker_event(
        organization_id=organization_id,
        job_id=job_id,
        kind=kind,
        action="worker_job_completed",
        job_try=job_try,
    )
    return result


async def worker_smoke_test(
    ctx: dict[str, Any],
    organization_id: int,
) -> dict[str, Any]:
    with tenant_scope(organization_id):
        async def operation() -> dict[str, Any]:
            await asyncio.sleep(0)
            return {
                "status": "completed",
                "organization_id": organization_id,
                "job_id": str(ctx.get("job_id") or "unknown"),
            }

        return await _run_audited_task(
            ctx,
            organization_id=organization_id,
            kind="worker_smoke_test",
            operation=operation,
        )
