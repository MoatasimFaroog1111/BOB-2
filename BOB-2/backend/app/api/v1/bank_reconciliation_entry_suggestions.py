from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.tenant_scope import current_organization_id
from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_suggestions import BankReconciliationSuggestionService

router = APIRouter()


class BankTxnForSuggestion(BaseModel):
    date: str = ""
    description: str = ""
    main_description: Optional[str] = None
    details: list[str] = Field(default_factory=list)
    reference: Optional[str] = None
    payment_ref: Optional[str] = None
    note: Optional[str] = None
    memo: Optional[str] = None
    currency: Optional[str] = None
    amount: float = 0.0
    debit: Optional[float] = None
    credit: Optional[float] = None
    row_number: Optional[int] = None
    suggested_action: Optional[str] = None
    suggested_action_label: Optional[str] = None
    explanation: Optional[str] = None
    detected_category: Optional[str] = None


class HistoricalEntrySuggestionRequest(BaseModel):
    transactions: list[BankTxnForSuggestion] = Field(default_factory=list)
    company_id: Optional[int] = None
    bank_journal_id: Optional[int] = None
    bank_account_id: Optional[int] = None
    history_limit: int = Field(default=600, ge=50, le=1500)
    semantic_limit: int = Field(default=8, ge=0, le=100)


@router.post("/bank-reconciliation/entry-suggestions")
def suggest_bank_reconciliation_entries(
    payload: HistoricalEntrySuggestionRequest,
    db: Session = Depends(get_db),
):
    organization_id = current_organization_id(required=True)
    context = SuggestionBatchContext(
        organization_id=organization_id,
        company_id=payload.company_id,
        bank_journal_id=payload.bank_journal_id,
        bank_account_id=payload.bank_account_id,
        history_limit=payload.history_limit,
        semantic_limit=payload.semantic_limit,
    )
    service = BankReconciliationSuggestionService(db, context)
    try:
        return service.suggest([transaction.model_dump() for transaction in payload.transactions])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to build bank reconciliation suggestions: {exc}",
        ) from exc
