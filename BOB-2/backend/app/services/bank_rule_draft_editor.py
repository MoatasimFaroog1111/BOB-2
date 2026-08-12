"""Edit unapproved Bank Rule versions while preserving immutable approved history."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.bank_rules import BankRule, BankRuleVersion
from app.models.core import AuditLog
from app.services.bank_rules_engine import BankRuleDefinitionError, validate_conditions


def _fingerprint(rule: BankRule, conditions: list[dict[str, Any]], target: dict[str, Any]) -> str:
    payload = {
        "name": rule.name,
        "journal_id": rule.journal_id,
        "company_id": rule.company_id,
        "priority": rule.priority,
        "conditions": conditions,
        "target": target,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class BankRuleDraftEditor:
    def update(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        rule_id: int,
        version_id: int,
        conditions: list[dict[str, Any]],
        target: dict[str, Any],
        rationale: str = "",
        change_note: str = "",
    ) -> BankRuleVersion:
        rule = (
            db.query(BankRule)
            .filter(BankRule.id == rule_id, BankRule.organization_id == organization_id)
            .first()
        )
        if not rule:
            raise HTTPException(status_code=404, detail="Bank Rule not found.")
        version = (
            db.query(BankRuleVersion)
            .filter(
                BankRuleVersion.id == version_id,
                BankRuleVersion.bank_rule_id == rule.id,
            )
            .first()
        )
        if not version:
            raise HTTPException(status_code=404, detail="Bank Rule version not found.")
        if version.approval_status != "draft":
            raise HTTPException(status_code=409, detail="Approved Bank Rule versions are immutable.")
        try:
            normalized = validate_conditions(conditions)
        except BankRuleDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        account_id = int(target.get("account_id") or 0)
        if account_id <= 0:
            raise HTTPException(status_code=422, detail="A counterpart Odoo account is required.")
        clean_target = {
            "account_id": account_id,
            "account_code": str(target.get("account_code") or ""),
            "account_name": str(target.get("account_name") or ""),
            "partner_id": int(target.get("partner_id") or 0) or None,
            "partner_name": str(target.get("partner_name") or ""),
            "analytic_account_id": int(target.get("analytic_account_id") or 0) or None,
            "analytic_account_name": str(target.get("analytic_account_name") or ""),
        }
        source_snapshot = dict(version.source_snapshot or {})
        source_snapshot["import_requires_manual_configuration"] = False
        source_snapshot["draft_last_edited_by_user_id"] = user_id
        version.conditions = normalized
        version.target = clean_target
        version.rationale = rationale.strip()[:4000] or version.rationale
        version.change_note = change_note.strip()[:4000] or version.change_note
        version.source_snapshot = source_snapshot
        version.fingerprint = _fingerprint(rule, normalized, clean_target)
        db.add(
            AuditLog(
                organization_id=organization_id,
                user_id=user_id,
                action="bank_rule.draft_edited",
                entity_type="bank_rule",
                entity_id=str(rule.id),
                details={
                    "version_id": version.id,
                    "version_number": version.version_number,
                    "fingerprint": version.fingerprint,
                },
            )
        )
        db.commit()
        db.refresh(version)
        return version


bank_rule_draft_editor = BankRuleDraftEditor()
