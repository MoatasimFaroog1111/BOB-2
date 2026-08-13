"""Tax configuration boundary for BOB Bank Rule drafts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.bank_rules import BankRule
from app.security.dependencies import require_permission
from app.services.bank_rule_draft_editor import bank_rule_draft_editor
from app.services.bank_rules_service import bank_rules_service
from app.services.tenant_erp_service import odoo_reference_validator, tenant_erp_resolver

router = APIRouter()


class BankRuleDraftTaxRequest(BaseModel):
    version_id: int = Field(gt=0)
    tax_id: int | None = Field(default=None, gt=0)


@router.patch("/bank-rules/{rule_id}/draft-tax")
def configure_bank_rule_draft_tax(
    rule_id: int,
    payload: BankRuleDraftTaxRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    organization_id = int(token["organization_id"])
    rule = (
        db.query(BankRule)
        .filter(BankRule.id == rule_id, BankRule.organization_id == organization_id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Bank Rule not found.")
    if payload.tax_id:
        _connection, erp = tenant_erp_resolver.resolve(db, organization_id)
        odoo_reference_validator.tax(
            erp,
            int(payload.tax_id),
            company_id=rule.company_id,
        )
    bank_rule_draft_editor.set_tax(
        db,
        organization_id=organization_id,
        user_id=int(token["user_id"]),
        rule_id=rule_id,
        version_id=payload.version_id,
        tax_id=payload.tax_id,
    )
    rows = bank_rules_service.list_rules(db, organization_id=organization_id, include_disabled=True)
    return next(row for row in rows if int(row["id"]) == int(rule_id))
