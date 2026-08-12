"""HTTP boundary for review-only daily bank accounting and audit packages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.dependencies import require_permission
from app.security.file_validation import sanitize_filename, validate_upload_file
from app.services.daily_bank_review_bob_rules import bob_daily_bank_review_service as daily_bank_review_service
from app.services.daily_bank_supporting_analysis import daily_bank_supporting_analysis_service
from app.services.daily_bank_supporting_evidence import daily_bank_supporting_evidence_service

router = APIRouter()


class SubmitDailyBankReviewRequest(BaseModel):
    document_id: int = Field(gt=0)
    journal_id: int = Field(gt=0)
    company_id: int | None = Field(default=None, gt=0)


class DailyBankReviewDecisionRequest(BaseModel):
    decision: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=4000)


@router.post("/daily-bank-review/prepare")
async def prepare_daily_bank_review(
    statement: UploadFile = File(...),
    journal_id: int = Form(...),
    company_id: int | None = Form(None),
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("upload_documents")),
):
    valid, error = await validate_upload_file(statement)
    if not valid:
        raise HTTPException(status_code=400, detail=error or "Bank statement validation failed.")
    content = await statement.read()
    await statement.seek(0)
    filename = sanitize_filename(statement.filename or "bank-statement")
    return daily_bank_review_service.prepare(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        filename=filename,
        content_type=statement.content_type,
        content=content,
        journal_id=journal_id,
        company_id=company_id,
    )


@router.post("/daily-bank-review/submit")
def submit_daily_bank_review(
    payload: SubmitDailyBankReviewRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("create_entries")),
):
    return daily_bank_review_service.submit(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        document_id=payload.document_id,
        journal_id=payload.journal_id,
        company_id=payload.company_id,
    )


@router.get("/daily-bank-review/queue")
def list_daily_bank_review_queue(
    limit: int = 100,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("view_financials")),
):
    return {
        "status": "success",
        "items": daily_bank_review_service.list_queue(
            db,
            organization_id=int(token["organization_id"]),
            limit=limit,
        ),
    }


@router.get("/daily-bank-review/{approval_id}")
def get_daily_bank_review(
    approval_id: int,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("view_financials")),
):
    return daily_bank_review_service.get_review(
        db,
        organization_id=int(token["organization_id"]),
        approval_id=approval_id,
    )


@router.post("/daily-bank-review/{approval_id}/supporting-documents")
async def attach_daily_bank_supporting_documents(
    approval_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("upload_documents")),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one supporting document is required.")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="A maximum of 20 supporting documents can be attached at once.")

    organization_id = int(token["organization_id"])
    user_id = int(token["user_id"])
    attached: list[dict] = []
    for upload in files:
        valid, error = await validate_upload_file(upload)
        if not valid:
            raise HTTPException(
                status_code=400,
                detail=f"{upload.filename or 'supporting document'}: {error or 'validation failed'}",
            )
        content = await upload.read()
        await upload.seek(0)
        evidence = daily_bank_supporting_evidence_service.attach(
            db,
            organization_id=organization_id,
            user_id=user_id,
            approval_id=approval_id,
            filename=sanitize_filename(upload.filename or "supporting-document"),
            content_type=upload.content_type,
            content=content,
        )
        evidence["analysis"] = daily_bank_supporting_analysis_service.analyze_attached_document(
            db,
            organization_id=organization_id,
            user_id=user_id,
            approval_id=approval_id,
            document_id=int(evidence["document_id"]),
        )
        attached.append(evidence)
    return {
        "status": "attached",
        "items": attached,
        "analysis_method": "local_document_ai_structured_fields",
        "external_llm_used": False,
        "safe_to_post": False,
    }


@router.get("/daily-bank-review/{approval_id}/supporting-documents")
def list_daily_bank_supporting_documents(
    approval_id: int,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("view_financials")),
):
    return {
        "status": "success",
        "items": daily_bank_supporting_evidence_service.list(
            db,
            organization_id=int(token["organization_id"]),
            approval_id=approval_id,
        ),
    }


@router.get("/daily-bank-review/{approval_id}/supporting-documents/{document_id}/content")
def get_daily_bank_supporting_document(
    approval_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("view_financials")),
):
    document, path = daily_bank_supporting_evidence_service.document_path(
        db,
        organization_id=int(token["organization_id"]),
        approval_id=approval_id,
        document_id=document_id,
    )
    return FileResponse(
        path=str(path),
        media_type=document.content_type or "application/octet-stream",
        filename=document.filename,
    )


@router.post("/daily-bank-review/{approval_id}/audit")
def audit_daily_bank_review(
    approval_id: int,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("review_entries")),
):
    organization_id = int(token["organization_id"])
    user_id = int(token["user_id"])
    daily_bank_review_service.audit(
        db,
        organization_id=organization_id,
        user_id=user_id,
        approval_id=approval_id,
    )
    daily_bank_supporting_evidence_service.merge_verification_into_audit(
        db,
        organization_id=organization_id,
        user_id=user_id,
        approval_id=approval_id,
    )
    daily_bank_supporting_analysis_service.merge_semantic_findings_into_audit(
        db,
        organization_id=organization_id,
        user_id=user_id,
        approval_id=approval_id,
    )
    return daily_bank_review_service.get_review(
        db,
        organization_id=organization_id,
        approval_id=approval_id,
    )


@router.post("/daily-bank-review/{approval_id}/decision")
def decide_daily_bank_review(
    approval_id: int,
    payload: DailyBankReviewDecisionRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("approve_actions")),
):
    return daily_bank_review_service.decide(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        approval_id=approval_id,
        decision=payload.decision,
        note=payload.note,
    )


@router.get("/daily-bank-review/documents/{document_id}/content")
def get_daily_bank_review_document(
    document_id: int,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("view_financials")),
):
    document, path = daily_bank_review_service.review_document_path(
        db,
        organization_id=int(token["organization_id"]),
        document_id=document_id,
    )
    return FileResponse(
        path=str(path),
        media_type=document.content_type or "application/octet-stream",
        filename=document.filename,
    )
