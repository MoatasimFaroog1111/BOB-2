"""Tenant-scoped background job status API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.tenant_scope import current_organization_id
from app.services.job_runs import get_job_run, load_job_result

router = APIRouter()


@router.get("/{job_id}")
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization_id = int(current_organization_id(required=True))
    run = get_job_run(
        db,
        organization_id=organization_id,
        job_id=job_id,
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Background job was not found.",
        )

    result = None
    if run.status == "completed":
        result = load_job_result(
            organization_id=organization_id,
            job_id=job_id,
        )
    return {
        "job_id": run.job_id,
        "kind": run.kind,
        "status": run.status,
        "progress": run.progress,
        "error_code": run.error_code,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "result": result,
    }
