from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.tenant_scope import current_organization_id
from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_evaluation_v2 import BankReconciliationEvaluationService

router = APIRouter()


@router.get("/bank-reconciliation/evaluation")
def evaluate_bank_reconciliation_predictions(
    company_id: int | None = Query(default=None, ge=1),
    bank_journal_id: int | None = Query(default=None, ge=1),
    bank_account_id: int | None = Query(default=None, ge=1),
    history_limit: int = Query(default=600, ge=100, le=1500),
    db: Session = Depends(get_db),
):
    """Run the accountant-grade leakage-safe evaluation against posted Odoo history.

    This endpoint is read-only. It does not create, edit, reconcile, draft, post,
    or otherwise mutate ERP records. Validation-only calibration targets 98% accepted
    account precision before the untouched Test partition is scored.
    """
    organization_id = current_organization_id(required=True)
    context = SuggestionBatchContext(
        organization_id=organization_id,
        company_id=company_id,
        bank_journal_id=bank_journal_id,
        bank_account_id=bank_account_id,
        history_limit=history_limit,
        semantic_limit=0,
    )
    try:
        return BankReconciliationEvaluationService(db, context).evaluate()
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bank reconciliation evaluation failed ({type(exc).__name__}).",
        ) from exc
