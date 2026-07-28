"""Asynchronous replacements for legacy long-running ERP HTTP handlers."""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.api.v1.erp import (
    ChatSpreadsheetRequest,
    bank_reconciliation as legacy_bank_reconciliation,
    chat_spreadsheet as legacy_chat_spreadsheet,
    match_documents as legacy_match_documents,
    parse_bank_statement_only as legacy_parse_bank_statement,
    upload_documents as legacy_upload_documents,
)
from app.db.database import get_db
from app.security.tenant_scope import current_organization_id
from app.services.job_queue import enqueue_background_job
from app.services.job_runs import (
    cleanup_job_uploads,
    create_job_run,
    persist_validated_uploads,
)

router = APIRouter()

_REPLACED_PATHS = frozenset(
    {
        "/upload-documents",
        "/match-documents",
        "/bank-reconciliation",
        "/bank-statement-parse",
        "/chat-spreadsheet",
    }
)


def replace_long_running_routes(legacy_router: APIRouter) -> None:
    legacy_router.routes[:] = [
        route
        for route in legacy_router.routes
        if not (isinstance(route, APIRoute) and route.path in _REPLACED_PATHS)
    ]


def _async_jobs_enabled() -> bool:
    return os.getenv("ASYNC_LONG_RUNNING_JOBS_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _queued_response(job_id: str, kind: str) -> dict[str, Any]:
    return {
        "status": "queued",
        "job_id": job_id,
        "kind": kind,
        "progress": 0,
    }


async def _queue_file_job(
    *,
    db: Session,
    files: list[UploadFile],
    kind: str,
    function_name: str,
    trailing_args: tuple[Any, ...] = (),
) -> dict[str, Any]:
    organization_id = int(current_organization_id(required=True))
    job_id = uuid.uuid4().hex
    persisted = await persist_validated_uploads(
        files,
        organization_id=organization_id,
        job_id=job_id,
    )
    create_job_run(
        db,
        organization_id=organization_id,
        kind=kind,
        job_id=job_id,
    )
    try:
        await enqueue_background_job(
            function_name=function_name,
            organization_id=organization_id,
            job_id=job_id,
            args=(persisted if len(persisted) > 1 else persisted[0], *trailing_args),
        )
    except Exception:
        cleanup_job_uploads(organization_id, job_id)
        raise
    return _queued_response(job_id, kind)


@router.post("/upload-documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    if not _async_jobs_enabled():
        return legacy_upload_documents(files)
    organization_id = int(current_organization_id(required=True))
    job_id = uuid.uuid4().hex
    persisted = await persist_validated_uploads(
        files,
        organization_id=organization_id,
        job_id=job_id,
    )
    create_job_run(
        db,
        organization_id=organization_id,
        kind="document_ocr",
        job_id=job_id,
    )
    try:
        await enqueue_background_job(
            function_name="process_documents_job",
            organization_id=organization_id,
            job_id=job_id,
            args=(persisted,),
        )
    except Exception:
        cleanup_job_uploads(organization_id, job_id)
        raise
    return _queued_response(job_id, "document_ocr")


@router.post("/match-documents", status_code=status.HTTP_202_ACCEPTED)
async def match_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    if not _async_jobs_enabled():
        return legacy_match_documents(files, db)
    organization_id = int(current_organization_id(required=True))
    job_id = uuid.uuid4().hex
    persisted = await persist_validated_uploads(
        files,
        organization_id=organization_id,
        job_id=job_id,
    )
    create_job_run(
        db,
        organization_id=organization_id,
        kind="document_matching",
        job_id=job_id,
    )
    try:
        await enqueue_background_job(
            function_name="match_documents_job",
            organization_id=organization_id,
            job_id=job_id,
            args=(persisted,),
        )
    except Exception:
        cleanup_job_uploads(organization_id, job_id)
        raise
    return _queued_response(job_id, "document_matching")


@router.post("/bank-statement-parse", status_code=status.HTTP_202_ACCEPTED)
async def parse_bank_statement(
    statement: UploadFile = File(...),
    date_from: str | None = Form(None),
    date_to: str | None = Form(None),
    company_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    if not _async_jobs_enabled():
        return await legacy_parse_bank_statement(statement, date_from, date_to, company_id)
    return await _queue_file_job(
        db=db,
        files=[statement],
        kind="bank_statement_parse",
        function_name="parse_bank_statement_job",
        trailing_args=(date_from, date_to),
    )


@router.post("/bank-reconciliation", status_code=status.HTTP_202_ACCEPTED)
async def bank_reconciliation(
    statement: UploadFile = File(...),
    db: Session = Depends(get_db),
    date_from: str | None = Form(None),
    date_to: str | None = Form(None),
    company_id: int | None = Form(None),
):
    if not _async_jobs_enabled():
        return legacy_bank_reconciliation(
            statement,
            db,
            date_from,
            date_to,
            company_id,
        )
    return await _queue_file_job(
        db=db,
        files=[statement],
        kind="bank_reconciliation",
        function_name="reconcile_bank_statement_job",
        trailing_args=(date_from, date_to, company_id),
    )


@router.post("/chat-spreadsheet", status_code=status.HTTP_202_ACCEPTED)
async def chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db: Session = Depends(get_db),
):
    if not _async_jobs_enabled():
        return legacy_chat_spreadsheet(payload, db)
    organization_id = int(current_organization_id(required=True))
    run = create_job_run(
        db,
        organization_id=organization_id,
        kind="spreadsheet_llm",
    )
    await enqueue_background_job(
        function_name="chat_spreadsheet_job",
        organization_id=organization_id,
        job_id=run.job_id,
        args=(payload.model_dump(mode="json"),),
    )
    return _queued_response(run.job_id, "spreadsheet_llm")
