"""Durable job metadata and temporary Redis result storage."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis_client import (
    RedisError,
    build_redis_key,
    get_redis_client,
    handle_redis_unavailable,
)
from app.models.job_run import JobRun
from app.security.file_validation import sanitize_filename, validate_upload_files

JOB_RESULT_TTL_SECONDS = 3600


def utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_job_run(
    db: Session,
    *,
    organization_id: int,
    kind: str,
    job_id: str | None = None,
) -> JobRun:
    run = JobRun(
        job_id=job_id or uuid.uuid4().hex,
        organization_id=organization_id,
        kind=kind,
        status="queued",
        progress=0,
        error_code=None,
        created_at=utc_naive(),
        finished_at=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_job_run(
    db: Session,
    *,
    organization_id: int,
    job_id: str,
) -> JobRun | None:
    return (
        db.query(JobRun)
        .filter(
            JobRun.job_id == job_id,
            JobRun.organization_id == organization_id,
        )
        .first()
    )


def update_job_run(
    *,
    organization_id: int,
    job_id: str,
    status_value: str,
    progress: int,
    error_code: str | None = None,
) -> None:
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        run = get_job_run(
            db,
            organization_id=organization_id,
            job_id=job_id,
        )
        if run is None:
            raise RuntimeError("job_run_missing")
        run.status = status_value
        run.progress = max(0, min(int(progress), 100))
        run.error_code = error_code[:100] if error_code else None
        if status_value in {"completed", "failed"}:
            run.finished_at = utc_naive()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _result_key(organization_id: int, job_id: str) -> str:
    return build_redis_key(
        "jobs",
        organization_id=organization_id,
        parts=("result", job_id),
    )


def store_job_result(
    *,
    organization_id: int,
    job_id: str,
    result: dict[str, Any],
) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        client.set(
            _result_key(organization_id, job_id),
            payload,
            ex=JOB_RESULT_TTL_SECONDS,
        )
    except RedisError as exc:
        handle_redis_unavailable(exc, component="job result storage")


def load_job_result(
    *,
    organization_id: int,
    job_id: str,
) -> dict[str, Any] | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_result_key(organization_id, job_id))
    except RedisError as exc:
        handle_redis_unavailable(exc, component="job result storage")
        return None
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def job_upload_directory(organization_id: int, job_id: str) -> Path:
    base = (settings.storage_path / "job_uploads").resolve()
    target = (base / str(organization_id) / job_id).resolve()
    if not target.is_relative_to(base):
        raise RuntimeError("job_upload_path_invalid")
    target.mkdir(parents=True, exist_ok=True)
    return target


async def persist_validated_uploads(
    files: list[UploadFile],
    *,
    organization_id: int,
    job_id: str,
) -> list[dict[str, str]]:
    if not files or len(files) > settings.MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload must contain between 1 and {settings.MAX_UPLOAD_FILES} files.",
        )

    validation = await validate_upload_files(files)
    rejected = [error for _file, valid, error in validation if not valid]
    if rejected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=rejected[0] or "File validation failed.",
        )

    directory = job_upload_directory(organization_id, job_id)
    persisted: list[dict[str, str]] = []
    try:
        for index, (upload, _valid, _error) in enumerate(validation, start=1):
            filename = sanitize_filename(upload.filename or f"upload-{index}")
            destination = directory / f"{index:03d}-{filename}"
            content = await upload.read()
            await upload.seek(0)
            destination.write_bytes(content)
            persisted.append(
                {
                    "path": str(destination),
                    "filename": filename,
                }
            )
        return persisted
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def cleanup_job_uploads(organization_id: int, job_id: str) -> None:
    shutil.rmtree(
        settings.storage_path / "job_uploads" / str(organization_id) / job_id,
        ignore_errors=True,
    )
