"""Tenant-scoped HTTP API for the BOB Bank Rules Engine."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.bank_reconciliation import parse_file
from app.security.dependencies import require_permission
from app.security.file_validation import sanitize_filename, validate_upload_file
from app.services.bank_rule_draft_editor import bank_rule_draft_editor
from app.services.bank_rules_service import bank_rules_service

router = APIRouter()


class BankRuleTargetInput(BaseModel):
    account_id: int = Field(gt=0)
    partner_id: int | None = Field(default=None, gt=0)
    analytic_account_id: int | None = Field(default=None, gt=0)


class BankRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    journal_id: int = Field(gt=0)
    company_id: int | None = Field(default=None, gt=0)
    priority: int = Field(default=100, ge=0, le=100000)
    conditions: list[dict[str, Any]] = Field(min_length=1, max_length=12)
    target: BankRuleTargetInput
    rationale: str = Field(default="", max_length=4000)
    change_note: str = Field(default="", max_length=4000)


class BankRuleDraftVersionRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    priority: int | None = Field(default=None, ge=0, le=100000)
    conditions: list[dict[str, Any]] = Field(min_length=1, max_length=12)
    target: BankRuleTargetInput
    rationale: str = Field(default="", max_length=4000)
    change_note: str = Field(default="", max_length=4000)


class BankRuleDraftEditRequest(BaseModel):
    version_id: int = Field(gt=0)
    conditions: list[dict[str, Any]] = Field(min_length=1, max_length=12)
    target: BankRuleTargetInput
    rationale: str = Field(default="", max_length=4000)
    change_note: str = Field(default="", max_length=4000)


class BankRuleApprovalRequest(BaseModel):
    version_id: int = Field(gt=0)
    approval_note: str = Field(default="", max_length=2000)


class BankRuleDisableRequest(BaseModel):
    reason: str = Field(default="", max_length=2000)


class OdooBankRuleImportRequest(BaseModel):
    journal_id: int = Field(gt=0)
    company_id: int | None = Field(default=None, gt=0)


@router.get("/bank-rules")
def list_bank_rules(
    journal_id: int | None = None,
    include_disabled: bool = True,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    return {
        "status": "success",
        "source_of_truth": "bob_bank_rules",
        "odoo_reference_role": "journals_accounts_partners_analytic_accounts_only",
        "items": bank_rules_service.list_rules(
            db,
            organization_id=int(token["organization_id"]),
            journal_id=journal_id,
            include_disabled=include_disabled,
        ),
    }


@router.post("/bank-rules")
def create_bank_rule(
    payload: BankRuleCreateRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    return bank_rules_service.create_rule(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        name=payload.name,
        journal_id=payload.journal_id,
        company_id=payload.company_id,
        priority=payload.priority,
        conditions=payload.conditions,
        target=payload.target.model_dump(),
        rationale=payload.rationale,
        change_note=payload.change_note,
    )


@router.post("/bank-rules/{rule_id}/versions")
def create_bank_rule_version(
    rule_id: int,
    payload: BankRuleDraftVersionRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    return bank_rules_service.create_draft_version(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        rule_id=rule_id,
        name=payload.name,
        priority=payload.priority,
        conditions=payload.conditions,
        target=payload.target.model_dump(),
        rationale=payload.rationale,
        change_note=payload.change_note,
    )


@router.patch("/bank-rules/{rule_id}/draft")
def edit_bank_rule_draft(
    rule_id: int,
    payload: BankRuleDraftEditRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    bank_rule_draft_editor.update(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        rule_id=rule_id,
        version_id=payload.version_id,
        conditions=payload.conditions,
        target=payload.target.model_dump(),
        rationale=payload.rationale,
        change_note=payload.change_note,
    )
    rules = bank_rules_service.list_rules(
        db,
        organization_id=int(token["organization_id"]),
        include_disabled=True,
    )
    return next(item for item in rules if int(item["id"]) == rule_id)


@router.post("/bank-rules/{rule_id}/approve")
def approve_bank_rule_version(
    rule_id: int,
    payload: BankRuleApprovalRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("approve_actions")),
):
    return bank_rules_service.approve_version(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        rule_id=rule_id,
        version_id=payload.version_id,
        approval_note=payload.approval_note,
    )


@router.post("/bank-rules/{rule_id}/disable")
def disable_bank_rule(
    rule_id: int,
    payload: BankRuleDisableRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    return bank_rules_service.disable_rule(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        rule_id=rule_id,
        reason=payload.reason,
    )


@router.post("/bank-rules/import-odoo")
def import_odoo_bank_rules(
    payload: OdooBankRuleImportRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    return bank_rules_service.import_from_odoo(
        db,
        organization_id=int(token["organization_id"]),
        user_id=int(token["user_id"]),
        journal_id=payload.journal_id,
        company_id=payload.company_id,
    )


@router.post("/bank-rules/{rule_id}/test")
async def test_bank_rule_against_statement(
    rule_id: int,
    statement: UploadFile = File(...),
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("manage_settings")),
):
    valid, error = await validate_upload_file(statement)
    if not valid:
        raise HTTPException(status_code=400, detail=error or "Bank statement validation failed.")
    content = await statement.read()
    await statement.seek(0)
    filename = sanitize_filename(statement.filename or "statement")
    suffix = os.path.splitext(filename)[1].lower()
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="bank-rule-test-", suffix=suffix, delete=False) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name
        transactions = parse_file(temp_path)
        if not transactions:
            raise HTTPException(status_code=422, detail="No bank transactions were found in the test statement.")
        return bank_rules_service.test_rule(
            db,
            organization_id=int(token["organization_id"]),
            rule_id=rule_id,
            transactions=transactions,
        )
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
