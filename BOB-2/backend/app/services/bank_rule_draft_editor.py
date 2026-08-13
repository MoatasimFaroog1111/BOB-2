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


_TAX_KEYS = (
    "tax_id", "tax_name", "tax_rate", "tax_amount_type", "tax_type_use",
    "tax_price_include", "tax_account_id", "tax_account_code", "tax_account_name",
    "tax_amount_mode", "tax_company_id",
)


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


def _clean_target(target: dict[str, Any]) -> dict[str, Any]:
    tax_id = int(target.get("tax_id") or 0) or None
    tax_account_id = (int(target.get("tax_account_id") or 0) or None) if tax_id else None
    return {
        "account_id": int(target.get("account_id") or 0) or None,
        "account_code": str(target.get("account_code") or ""),
        "account_name": str(target.get("account_name") or ""),
        "partner_id": int(target.get("partner_id") or 0) or None,
        "partner_name": str(target.get("partner_name") or ""),
        "analytic_account_id": int(target.get("analytic_account_id") or 0) or None,
        "analytic_account_name": str(target.get("analytic_account_name") or ""),
        "tax_id": tax_id,
        "tax_name": str(target.get("tax_name") or "") if tax_id else "",
        "tax_rate": target.get("tax_rate") if tax_id else None,
        "tax_amount_type": str(target.get("tax_amount_type") or "") if tax_id else "",
        "tax_type_use": str(target.get("tax_type_use") or "") if tax_id else "",
        "tax_price_include": bool(target.get("tax_price_include")) if tax_id else False,
        "tax_account_id": tax_account_id,
        "tax_account_code": str(target.get("tax_account_code") or "") if tax_id else "",
        "tax_account_name": str(target.get("tax_account_name") or "") if tax_id else "",
        "tax_amount_mode": "included_in_bank_amount" if tax_id else None,
        "tax_company_id": target.get("tax_company_id") if tax_id else None,
    }


class BankRuleDraftEditor:
    @staticmethod
    def _rule_and_version(
        db: Session,
        *,
        organization_id: int,
        rule_id: int,
        version_id: int,
    ) -> tuple[BankRule, BankRuleVersion]:
        rule = (
            db.query(BankRule)
            .filter(BankRule.id == rule_id, BankRule.organization_id == organization_id)
            .first()
        )
        if not rule:
            raise HTTPException(status_code=404, detail="Bank Rule not found.")
        version = (
            db.query(BankRuleVersion)
            .filter(BankRuleVersion.id == version_id, BankRuleVersion.bank_rule_id == rule.id)
            .first()
        )
        if not version:
            raise HTTPException(status_code=404, detail="Bank Rule version not found.")
        if version.approval_status != "draft":
            raise HTTPException(status_code=409, detail="Approved Bank Rule versions are immutable.")
        return rule, version

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
        rule, version = self._rule_and_version(
            db,
            organization_id=organization_id,
            rule_id=rule_id,
            version_id=version_id,
        )
        try:
            normalized = validate_conditions(conditions)
        except BankRuleDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clean_target = _clean_target(target)
        if not clean_target["account_id"]:
            raise HTTPException(status_code=422, detail="A counterpart Odoo account is required.")
        # The legacy editor intentionally owns account/partner/analytic fields only.
        # Preserve tax configured by the dedicated tax component unless the caller
        # explicitly includes tax_id in its target contract.
        if "tax_id" not in target:
            existing_target = dict(version.target or {})
            for key in _TAX_KEYS:
                if key in existing_target:
                    clean_target[key] = existing_target[key]
        elif clean_target["tax_id"]:
            clean_target["tax_company_id"] = rule.company_id
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
                    "tax_id": clean_target.get("tax_id"),
                    "fingerprint": version.fingerprint,
                },
            )
        )
        db.commit()
        db.refresh(version)
        return version

    def set_tax(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        rule_id: int,
        version_id: int,
        tax_id: int | None,
    ) -> BankRuleVersion:
        """Attach/clear tax intent on a draft created by the core versioning service."""
        rule, version = self._rule_and_version(
            db,
            organization_id=organization_id,
            rule_id=rule_id,
            version_id=version_id,
        )
        target = dict(version.target or {})
        for key in _TAX_KEYS:
            target.pop(key, None)
        selected = int(tax_id or 0)
        if selected > 0:
            target.update({
                "tax_id": selected,
                "tax_name": "",
                "tax_rate": None,
                "tax_amount_type": "",
                "tax_type_use": "",
                "tax_price_include": False,
                "tax_account_id": None,
                "tax_account_code": "",
                "tax_account_name": "",
                "tax_amount_mode": "included_in_bank_amount",
                "tax_company_id": rule.company_id,
            })
        version.target = target
        version.fingerprint = _fingerprint(rule, list(version.conditions or []), target)
        db.add(
            AuditLog(
                organization_id=organization_id,
                user_id=user_id,
                action="bank_rule.draft_tax_configured",
                entity_type="bank_rule",
                entity_id=str(rule.id),
                details={"version_id": version.id, "tax_id": selected or None, "fingerprint": version.fingerprint},
            )
        )
        db.commit()
        db.refresh(version)
        return version


bank_rule_draft_editor = BankRuleDraftEditor()
