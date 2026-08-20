from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.accounting_draft_adapter import AccountingDraftWriteError
from app.erp.accounting_draft_attachment_adapter import (
    AccountingDraftAttachmentError,
    OdooAccountingDraftAttachmentAdapter,
)
from app.erp.accounting_draft_preflight import AccountingDraftPreflightError
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposalError
from app.security.dependencies import require_permission
from app.security.file_validation import validate_upload_file
from app.services.accounting_document_review import AccountingDocumentReviewService
from app.services.accounting_human_reviewed_draft import AccountingHumanReviewedDraftService
from app.services.accounting_intelligence import AccountingIntelligenceService
from app.services.accounting_ml_draft_service import AccountingMLDraftService
from app.services.accounting_persisted_inference import AccountingPersistedInferenceService
from app.services.tenant_erp import organization_id_from_principal
from app.services.tenant_erp_service import tenant_erp_resolver

router = APIRouter()


class LearningSyncRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    limit: int = Field(default=1000, ge=1, le=5000)
    company_id: int | None = Field(default=None, ge=1)
    include_attachment_content: bool = True
    attachment_content_limit: int = Field(default=100, ge=1, le=500)


class AccountingDocumentFeatureHint(BaseModel):
    """Non-target document metadata matching the persisted model input contract."""

    extension: str | None = Field(default=None, max_length=40)
    mime: str | None = Field(default=None, max_length=160)
    extractor: str | None = Field(default=None, max_length=120)
    ocr_pages: int = Field(default=0, ge=0, le=10000)


class AccountingInterpretRequest(BaseModel):
    text: str = Field(..., min_length=4, max_length=100000)
    channel: Literal[
        "document",
        "ocr",
        "chat",
        "voice",
        "telegram",
        "spreadsheet",
        "api",
        "manual",
    ] = "manual"
    amount: float | None = None
    move_type_hint: str | None = Field(default=None, max_length=80)
    currency_hint: str | None = Field(default=None, max_length=20)
    company_id: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=12, ge=1, le=50)
    documents: list[AccountingDocumentFeatureHint] = Field(default_factory=list, max_length=50)


class AccountingDraftCreateRequest(BaseModel):
    """Explicit draft/preflight request; predictions are recomputed server-side."""

    text: str = Field(..., min_length=4, max_length=100000)
    channel: Literal["document", "ocr"]
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    company_id: int = Field(..., ge=1)
    source_reference: str = Field(..., min_length=3, max_length=240)
    entry_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str | None = Field(default=None, max_length=500)
    top_k: int = Field(default=10, ge=1, le=10)
    documents: list[AccountingDocumentFeatureHint] = Field(default_factory=list, max_length=50)


@router.get("/status")
def accounting_intelligence_status(
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("view_financials")),
    company_id: int | None = Query(default=None, ge=1),
):
    organization_id = organization_id_from_principal(principal)
    return AccountingPersistedInferenceService(db).status(
        organization_id=organization_id,
        company_id=company_id,
    )


@router.post("/learn/sync")
def sync_accounting_learning(
    payload: LearningSyncRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("manage_settings")),
):
    """Index posted ERP history and optional guarded attachment text as learning evidence."""
    organization_id = organization_id_from_principal(principal)
    try:
        return AccountingIntelligenceService(db).sync_historical_learning(
            organization_id=organization_id,
            date_from=payload.date_from,
            date_to=payload.date_to,
            limit=payload.limit,
            company_id=payload.company_id,
            include_attachment_content=payload.include_attachment_content,
            attachment_content_limit=payload.attachment_content_limit,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Accounting learning sync failed ({type(exc).__name__}).",
        ) from exc


@router.post("/interpret")
def interpret_accounting_input(
    payload: AccountingInterpretRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("create_entries")),
):
    """Read-only channel-neutral accounting interpretation."""
    organization_id = organization_id_from_principal(principal)
    try:
        result = AccountingPersistedInferenceService(db).predict(
            organization_id=organization_id,
            text=payload.text,
            channel=payload.channel,
            amount=payload.amount,
            move_type_hint=payload.move_type_hint,
            currency_hint=payload.currency_hint,
            company_id=payload.company_id,
            top_k=payload.top_k,
            documents=[item.model_dump(exclude_none=True) for item in payload.documents],
        )
        return {
            "status": "success",
            "channel": payload.channel,
            "prediction": result,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Accounting intelligence interpretation failed ({type(exc).__name__}).",
        ) from exc


def _draft_service_kwargs(payload: AccountingDraftCreateRequest) -> dict:
    return {
        "text": payload.text,
        "channel": payload.channel,
        "amount": payload.amount,
        "company_id": payload.company_id,
        "source_reference": payload.source_reference,
        "entry_date": payload.entry_date,
        "description": payload.description,
        "documents": [item.model_dump(exclude_none=True) for item in payload.documents],
        "top_k": payload.top_k,
    }


def _raise_draft_policy_error(exc: Exception) -> None:
    if isinstance(exc, AccountingDraftProposalError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    if isinstance(exc, AccountingDraftPreflightError):
        conflict_codes = {
            "DUPLICATE_IDEMPOTENCY_REFERENCE",
            "IDEMPOTENCY_REFERENCE_ALREADY_POSTED",
        }
        raise HTTPException(
            status_code=(status.HTTP_409_CONFLICT if exc.code in conflict_codes else status.HTTP_422_UNPROCESSABLE_ENTITY),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    if isinstance(exc, AccountingDraftWriteError):
        conflict_codes = {
            "ODOO_DUPLICATE_IDEMPOTENCY_REF",
            "ODOO_IDEMPOTENCY_REF_NOT_DRAFT",
        }
        raise HTTPException(
            status_code=(status.HTTP_409_CONFLICT if exc.code in conflict_codes else status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    if isinstance(exc, AccountingDraftAttachmentError):
        conflict_codes = {"ODOO_DUPLICATE_SOURCE_ATTACHMENTS"}
        raise HTTPException(
            status_code=(status.HTTP_409_CONFLICT if exc.code in conflict_codes else status.HTTP_422_UNPROCESSABLE_ENTITY),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "DRAFT_POLICY_REJECTED", "message": str(exc)},
        ) from exc
    raise exc


async def _validated_review_upload(file: UploadFile) -> bytes:
    is_valid, validation_error = await validate_upload_file(file)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "DOCUMENT_VALIDATION_FAILED", "message": validation_error or "Document validation failed."},
        )
    limit = OdooAccountingDraftAttachmentAdapter.MAX_ATTACHMENT_BYTES
    content = await file.read(limit + 1)
    await file.seek(0)
    if len(content) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "ATTACHMENT_TOO_LARGE", "message": "Source document exceeds the 25 MiB review limit."},
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "DOCUMENT_EMPTY", "message": "Source document is empty."},
        )
    return content


def _reviewer_identity(principal: dict) -> dict:
    return {
        key: principal.get(key)
        for key in ("user_id", "sub", "email", "role")
        if principal.get(key) not in (None, "")
    }


@router.post("/draft/preflight")
def preflight_accounting_ml_odoo_draft(
    payload: AccountingDraftCreateRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("create_entries")),
):
    """Run the exact ML/gate/proposal path and live Odoo checks without mutation."""
    organization_id = organization_id_from_principal(principal)
    try:
        return AccountingMLDraftService(db).preflight(
            organization_id=organization_id,
            **_draft_service_kwargs(payload),
        )
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _raise_draft_policy_error(exc)
        except HTTPException:
            raise
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Accounting ML draft preflight failed ({type(exc).__name__}).",
        ) from exc


@router.post("/draft/create")
def create_accounting_ml_odoo_draft(
    payload: AccountingDraftCreateRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("create_entries")),
):
    """Create one idempotent Odoo draft after locked ML and live preflight pass.

    The server recomputes inference and the safety gate. The client cannot submit
    account IDs or a prebuilt prediction. This endpoint has no posting operation.
    Tax remains review-only. Partner and analytic enrichment are applied only when
    the conservative enrichment policy and live Odoo preflight both approve them.
    """
    organization_id = organization_id_from_principal(principal)
    try:
        return AccountingMLDraftService(db).create_draft(
            organization_id=organization_id,
            **_draft_service_kwargs(payload),
        )
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _raise_draft_policy_error(exc)
        except HTTPException:
            raise
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Accounting ML draft creation failed ({type(exc).__name__}).",
        ) from exc


@router.post("/draft/review/analyze")
async def analyze_accounting_document_for_review(
    file: UploadFile = File(...),
    company_id: int = Form(..., ge=1),
    amount: Decimal | None = Form(default=None),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("create_entries")),
):
    """Analyze a validated source document and expose V2 recommendations for review.

    This endpoint is strictly read-only with respect to Odoo. The deterministic
    decision gate is returned unchanged even when it requires human review.
    """
    organization_id = organization_id_from_principal(principal)
    content = await _validated_review_upload(file)
    try:
        return AccountingDocumentReviewService(db).analyze(
            organization_id=organization_id,
            company_id=company_id,
            filename=file.filename or "source-document",
            mimetype=file.content_type or "application/octet-stream",
            content=content,
            amount_override=(float(amount) if amount is not None else None),
        )
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _raise_draft_policy_error(exc)
        except HTTPException:
            raise
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Accounting document review analysis failed ({type(exc).__name__}).",
        ) from exc


@router.post("/draft/review/create")
async def create_human_reviewed_accounting_draft(
    file: UploadFile = File(...),
    company_id: int = Form(..., ge=1),
    amount: Decimal = Form(..., gt=0),
    entry_date: str = Form(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    journal_id: int = Form(..., ge=1),
    debit_account_id: int = Form(..., ge=1),
    credit_account_id: int = Form(..., ge=1),
    debit_partner_id: int | None = Form(default=None, ge=1),
    credit_partner_id: int | None = Form(default=None, ge=1),
    debit_analytic_id: int | None = Form(default=None, ge=1),
    credit_analytic_id: int | None = Form(default=None, ge=1),
    description: str | None = Form(default=None, max_length=500),
    reviewer_acknowledged: bool = Form(default=False),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("create_entries")),
):
    """Create/reuse one reviewed Odoo draft and attach the original source document.

    This is the only endpoint that accepts reviewer-selected accounting IDs. It
    requires an explicit acknowledgement, reruns persisted V2 from the uploaded
    bytes, preserves the original gate in the audit, resolves every selected ID
    from the company-scoped live Odoo catalog, executes live preflight, creates only
    a draft, and has no posting method.
    """
    if not reviewer_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "HUMAN_REVIEW_ACKNOWLEDGEMENT_REQUIRED",
                "message": "The accountant must explicitly acknowledge the reviewed draft before creation.",
            },
        )

    organization_id = organization_id_from_principal(principal)
    content = await _validated_review_upload(file)
    try:
        return AccountingHumanReviewedDraftService(db).create(
            organization_id=organization_id,
            company_id=company_id,
            filename=file.filename or "source-document",
            mimetype=file.content_type or "application/octet-stream",
            content=content,
            amount=amount,
            entry_date=entry_date,
            description=description,
            journal_id=journal_id,
            debit_account_id=debit_account_id,
            credit_account_id=credit_account_id,
            debit_partner_id=debit_partner_id,
            credit_partner_id=credit_partner_id,
            debit_analytic_id=debit_analytic_id,
            credit_analytic_id=credit_analytic_id,
            reviewer=_reviewer_identity(principal),
        )
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _raise_draft_policy_error(exc)
        except HTTPException:
            raise
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Human-reviewed accounting draft creation failed ({type(exc).__name__}).",
        ) from exc


@router.post("/draft/{move_id}/attachment")
def attach_source_document_to_accounting_draft(
    move_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("create_entries")),
):
    """Attach the original source document to an existing unposted Odoo draft.

    This is an idempotent document-link operation only. It cannot post or otherwise
    confirm the journal entry, and the attachment adapter refuses non-draft moves.
    """
    organization_id = organization_id_from_principal(principal)
    try:
        connection, erp = tenant_erp_resolver.resolve(db, organization_id)
        provider_name = str(getattr(connection, "provider", "") or "").strip().lower()
        if provider_name != "odoo":
            raise ValueError("Accounting draft source attachments currently support Odoo only.")

        limit = OdooAccountingDraftAttachmentAdapter.MAX_ATTACHMENT_BYTES
        content = file.file.read(limit + 1)
        if len(content) > limit:
            raise AccountingDraftAttachmentError(
                "ATTACHMENT_TOO_LARGE",
                "Source document exceeds the 25 MiB draft-attachment limit.",
            )
        result = OdooAccountingDraftAttachmentAdapter(erp).attach(
            move_id=move_id,
            filename=file.filename or "source-document",
            mimetype=file.content_type or "application/octet-stream",
            content=content,
        )
        return {
            "status": "success",
            "attachment": result,
            "safety": {
                "target_state_required": "draft",
                "posting_method_invoked": False,
                "auto_posted_to_erp": False,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _raise_draft_policy_error(exc)
        except HTTPException:
            raise
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Accounting draft attachment failed ({type(exc).__name__}).",
        ) from exc
