from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.bank_rule_suggestions import fetch_odoo_bank_rules
from app.security.tenant_scope import current_organization_id
from app.services.tenant_erp_service import tenant_erp_resolver

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
    organization_id = current_organization_id(required=True)
    _connection, erp = tenant_erp_resolver.resolve(db, organization_id)
    rules = fetch_odoo_bank_rules(
        erp,
        company_id=company_id,
        bank_journal_id=bank_journal_id,
        limit=200,
    )
    return {
        "status": "success",
        "items": rules,
        "count": len(rules),
        "method": "odoo_bank_rules",
    }
