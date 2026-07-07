from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/bank-reconciliation/bank-rule-entry-suggestions/health")
def bank_rule_entry_suggestions_health():
    return {"status": "success"}
