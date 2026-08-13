from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.dependencies import require_permission
from app.services.accounting_intelligence import AccountingIntelligenceService
from app.services.tenant_erp import organization_id_from_principal

router = APIRouter()


class LearningSyncRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    limit: int = Field(default=1000, ge=1, le=5000)
    company_id: int | None = Field(default=None, ge=1)


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
    top_k: int = Field(default=12, ge=1, le=50)


@router.get("/status")
def accounting_intelligence_status(
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("view_financials")),
):
    organization_id = organization_id_from_principal(principal)
    return AccountingIntelligenceService(db).status(organization_id=organization_id)


@router.post("/learn/sync")
def sync_accounting_learning(
    payload: LearningSyncRequest,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_permission("manage_settings")),
):
    """Index posted ERP history as read-only accounting learning examples."""
    organization_id = organization_id_from_principal(principal)
    try:
        return AccountingIntelligenceService(db).sync_historical_learning(
            organization_id=organization_id,
            date_from=payload.date_from,
            date_to=payload.date_to,
            limit=payload.limit,
            company_id=payload.company_id,
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
    """Channel-neutral accounting interpretation for documents, chat, or voice text.

    This endpoint only returns learned recommendations and audit warnings.  It
    never posts or mutates the connected ERP.
    """
    organization_id = organization_id_from_principal(principal)
    try:
        result = AccountingIntelligenceService(db).predict(
            organization_id=organization_id,
            text=payload.text,
            amount=payload.amount,
            move_type_hint=payload.move_type_hint,
            currency_hint=payload.currency_hint,
            top_k=payload.top_k,
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
