from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.accounting_draft_adapter import AccountingDraftWriteError
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposalError
from app.security.dependencies import require_permission
from app.services.accounting_intelligence import AccountingIntelligenceService
from app.services.accounting_ml_draft_service import AccountingMLDraftService
from app.services.accounting_persisted_inference import AccountingPersistedInferenceService
from app.services.tenant_erp import organization_id_from_principal

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
    """Explicit mutation request; predictions are recomputed server-side."""

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
):
    organization_id = organization_id_from_principal(principal)
    return AccountingPersistedInferenceService(db).status(organization_id=organization_id)


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
    """Read-only channel-neutral accounting interpretation.

    Document/OCR inputs use the cryptographically verified persisted V2 bundle in
    Load -> Predict mode. Other channels retain the historical semantic engine.
    This endpoint never posts or mutates the connected ERP.
    """
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


@router.post("/draft/create")
def create_accounting_ml_odoo_draft(
    payload: AccountingDraftCreateRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("create_entries")),
):
    """Create one idempotent Odoo *draft* after the locked ML gate passes.

    The server recomputes inference and the safety gate. The client cannot submit
    account IDs or a prebuilt prediction. This endpoint has no posting operation.
    Taxes, analytics, and partners remain recommendations only in this first phase.
    """
    organization_id = organization_id_from_principal(principal)
    try:
        return AccountingMLDraftService(db).create_draft(
            organization_id=organization_id,
            text=payload.text,
            channel=payload.channel,
            amount=payload.amount,
            company_id=payload.company_id,
            source_reference=payload.source_reference,
            entry_date=payload.entry_date,
            description=payload.description,
            documents=[item.model_dump(exclude_none=True) for item in payload.documents],
            top_k=payload.top_k,
        )
    except AccountingDraftProposalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AccountingDraftWriteError as exc:
        conflict_codes = {
            "ODOO_DUPLICATE_IDEMPOTENCY_REF",
            "ODOO_IDEMPOTENCY_REF_NOT_DRAFT",
        }
        raise HTTPException(
            status_code=(status.HTTP_409_CONFLICT if exc.code in conflict_codes else status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "DRAFT_POLICY_REJECTED", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Accounting ML draft creation failed ({type(exc).__name__}).",
        ) from exc
