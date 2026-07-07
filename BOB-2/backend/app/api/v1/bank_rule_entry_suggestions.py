from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.bank_reconciliation_entry_suggestions import _get_active_erp_provider
from app.db.database import get_db
from app.erp.bank_rule_suggestions import fetch_odoo_bank_rules

router = APIRouter()


@router.get("/bank-reconciliation/bank-rule-entry-suggestions/health")
def bank_rule_entry_suggestions_health():
    return {"status": "success"}


@router.get("/bank-reconciliation/bank-rules")
def get_bank_reconciliation_rules(
    company_id: int | None = None,
    bank_journal_id: int | None = None,
    db: Session = Depends(get_db),
):
    erp = _get_active_erp_provider(db)
    rules = fetch_odoo_bank_rules(erp, company_id=company_id, bank_journal_id=bank_journal_id, limit=200)
    return {"status": "success", "items": rules, "count": len(rules), "method": "odoo_bank_rules"}
