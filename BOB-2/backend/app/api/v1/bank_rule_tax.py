"""Tax configuration boundary for BOB Bank Rule drafts."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.dependencies import require_permission
from app.services.bank_rule_draft_editor import bank_rule_draft_editor
from app.services.bank_rules_service import bank_rules_service

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
