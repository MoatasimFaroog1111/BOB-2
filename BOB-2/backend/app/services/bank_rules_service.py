"""Application service for tenant-owned, versioned BOB Bank Rules."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.erp.bank_rule_suggestions import fetch_odoo_bank_rules
from app.models.bank_rules import BankRule, BankRuleVersion
from app.models.core import AuditLog
from app.services.bank_rules_engine import (
    BankRuleDefinitionError,
    bank_rules_engine,
    validate_conditions,
)
from app.services.tenant_erp_service import (
    OdooReferenceValidator,
    TenantERPResolver,
    odoo_reference_validator,
    tenant_erp_resolver,
)


DRAFT = "draft"
APPROVED = "approved"
SUPERSEDED = "superseded"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _m2o(value: Any) -> tuple[int | None, str]:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0]), str(value[1] if len(value) > 1 else "")
        except (TypeError, ValueError):
            return None, ""
    if isinstance(value, int):
        return value, ""
    return None, ""


class BankRulesService:
    def __init__(
        self,
        *,
        erp_resolver: TenantERPResolver | None = None,
        reference_validator: OdooReferenceValidator | None = None,
    ) -> None:
        self._erp_resolver = erp_resolver or tenant_erp_resolver
        self._references = reference_validator or odoo_reference_validator

    @staticmethod
    def _audit(
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        action: str,
        entity_id: int | None,
        details: dict[str, Any],
    ) -> None:
        db.add(
            AuditLog(
                organization_id=organization_id,
                user_id=user_id,
                action=action,
                entity_type="bank_rule",
                entity_id=str(entity_id) if entity_id is not None else None,
                details=details,
            )
        )

    @staticmethod
    def _rule(db: Session, organization_id: int, rule_id: int) -> BankRule:
        row = (
            db.query(BankRule)
            .filter(BankRule.id == rule_id, BankRule.organization_id == organization_id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Bank Rule not found.")
        return row

    @staticmethod
    def _version(db: Session, rule_id: int, version_id: int) -> BankRuleVersion:
        row = (
            db.query(BankRuleVersion)
            .filter(BankRuleVersion.id == version_id, BankRuleVersion.bank_rule_id == rule_id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Bank Rule version not found.")
        return row

    @staticmethod
    def _latest_version(db: Session, rule_id: int, status: str | None = None) -> BankRuleVersion | None:
        query = db.query(BankRuleVersion).filter(BankRuleVersion.bank_rule_id == rule_id)
        if status:
            query = query.filter(BankRuleVersion.approval_status == status)
        return query.order_by(BankRuleVersion.version_number.desc()).first()

    @staticmethod
    def _next_version(db: Session, rule_id: int) -> int:
        maximum = (
            db.query(func.max(BankRuleVersion.version_number))
            .filter(BankRuleVersion.bank_rule_id == rule_id)
            .scalar()
        )
        return int(maximum or 0) + 1

    @staticmethod
    def _fingerprint(
        *,
        name: str,
        journal_id: int,
        company_id: int | None,
        priority: int,
        conditions: list[dict[str, Any]],
        target: dict[str, Any],
    ) -> str:
        return _canonical_hash(
            {
                "name": name,
                "journal_id": journal_id,
                "company_id": company_id,
                "priority": priority,
                "conditions": conditions,
                "target": target,
            }
        )

    @staticmethod
    def _serialize_version(version: BankRuleVersion | None) -> dict[str, Any] | None:
        if not version:
            return None
        return {
            "id": version.id,
            "version_number": version.version_number,
            "approval_status": version.approval_status,
            "conditions": version.conditions or [],
            "target": version.target or {},
            "rationale": version.rationale,
            "change_note": version.change_note,
            "source_snapshot": version.source_snapshot or {},
            "fingerprint": version.fingerprint,
            "created_by_user_id": version.created_by_user_id,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "approved_by_user_id": version.approved_by_user_id,
            "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        }

    def serialize_rule(self, db: Session, rule: BankRule) -> dict[str, Any]:
        approved = self._latest_version(db, rule.id, APPROVED)
        draft = self._latest_version(db, rule.id, DRAFT)
        latest = self._latest_version(db, rule.id)
        return {
            "id": rule.id,
            "name": rule.name,
            "journal_id": rule.journal_id,
            "company_id": rule.company_id,
            "priority": rule.priority,
            "is_enabled": rule.is_enabled,
            "source_system": rule.source_system,
            "source_external_id": rule.source_external_id,
            "created_by_user_id": rule.created_by_user_id,
            "created_at": rule.created_at.isoformat() if rule.created_at else None,
            "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
            "latest_version": self._serialize_version(latest),
            "approved_version": self._serialize_version(approved),
            "draft_version": self._serialize_version(draft),
        }

    def list_rules(
        self,
        db: Session,
        *,
        organization_id: int,
        journal_id: int | None = None,
        include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        query = db.query(BankRule).filter(BankRule.organization_id == organization_id)
        if journal_id:
            query = query.filter(BankRule.journal_id == journal_id)
        if not include_disabled:
            query = query.filter(BankRule.is_enabled.is_(True))
        rows = query.order_by(BankRule.priority.asc(), BankRule.id.asc()).all()
        return [self.serialize_rule(db, row) for row in rows]

    def create_rule(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        name: str,
        journal_id: int,
        company_id: int | None,
        priority: int,
        conditions: list[dict[str, Any]],
        target: dict[str, Any],
        rationale: str = "",
        change_note: str = "",
        source_system: str = "bob",
        source_external_id: str | None = None,
        source_snapshot: dict[str, Any] | None = None,
        validate_definition: bool = True,
    ) -> dict[str, Any]:
        clean_name = " ".join(name.split()).strip()
        if not clean_name or len(clean_name) > 200:
            raise HTTPException(status_code=422, detail="Bank Rule name must contain 1-200 characters.")
        if journal_id <= 0:
            raise HTTPException(status_code=422, detail="A valid bank journal ID is required.")
        if priority < 0 or priority > 100000:
            raise HTTPException(status_code=422, detail="Priority must be between 0 and 100000.")
        try:
            normalized_conditions = validate_conditions(conditions) if validate_definition else list(conditions or [])
        except BankRuleDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clean_target = {
            "account_id": int(target.get("account_id") or 0) or None,
            "account_code": str(target.get("account_code") or ""),
            "account_name": str(target.get("account_name") or ""),
            "partner_id": int(target.get("partner_id") or 0) or None,
            "partner_name": str(target.get("partner_name") or ""),
            "analytic_account_id": int(target.get("analytic_account_id") or 0) or None,
            "analytic_account_name": str(target.get("analytic_account_name") or ""),
        }
        if validate_definition and not clean_target["account_id"]:
            raise HTTPException(status_code=422, detail="A counterpart Odoo account is required.")

        duplicate = (
            db.query(BankRule)
            .filter(
                BankRule.organization_id == organization_id,
                BankRule.journal_id == journal_id,
                BankRule.name == clean_name,
            )
            .filter(BankRule.company_id == company_id if company_id is not None else BankRule.company_id.is_(None))
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="A Bank Rule with this name already exists for the journal/company.")

        rule = BankRule(
            organization_id=organization_id,
            name=clean_name,
            journal_id=journal_id,
            company_id=company_id,
            priority=priority,
            is_enabled=False,
            source_system=source_system,
            source_external_id=source_external_id,
            created_by_user_id=user_id,
        )
        db.add(rule)
        db.flush()
        fingerprint = self._fingerprint(
            name=clean_name,
            journal_id=journal_id,
            company_id=company_id,
            priority=priority,
            conditions=normalized_conditions,
            target=clean_target,
        )
        version = BankRuleVersion(
            bank_rule_id=rule.id,
            version_number=1,
            approval_status=DRAFT,
            conditions=normalized_conditions,
            target=clean_target,
            rationale=rationale.strip()[:4000] or None,
            change_note=change_note.strip()[:4000] or None,
            source_snapshot=source_snapshot or {},
            fingerprint=fingerprint,
            created_by_user_id=user_id,
            created_at=_utc_now(),
        )
        db.add(version)
        db.flush()
        self._audit(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="bank_rule.created",
            entity_id=rule.id,
            details={
                "version_id": version.id,
                "version_number": 1,
                "journal_id": journal_id,
                "company_id": company_id,
                "priority": priority,
                "source_system": source_system,
                "fingerprint": fingerprint,
            },
        )
        db.commit()
        return self.serialize_rule(db, rule)

    def create_draft_version(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        rule_id: int,
        name: str | None,
        priority: int | None,
        conditions: list[dict[str, Any]],
        target: dict[str, Any],
        rationale: str = "",
        change_note: str = "",
    ) -> dict[str, Any]:
        rule = self._rule(db, organization_id, rule_id)
        if self._latest_version(db, rule.id, DRAFT):
            raise HTTPException(status_code=409, detail="This Bank Rule already has a draft version awaiting review.")
        try:
            normalized_conditions = validate_conditions(conditions)
        except BankRuleDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        next_name = " ".join((name or rule.name).split()).strip()
        next_priority = rule.priority if priority is None else int(priority)
        if next_priority < 0 or next_priority > 100000:
            raise HTTPException(status_code=422, detail="Priority must be between 0 and 100000.")
        clean_target = {
            "account_id": int(target.get("account_id") or 0) or None,
            "account_code": str(target.get("account_code") or ""),
            "account_name": str(target.get("account_name") or ""),
            "partner_id": int(target.get("partner_id") or 0) or None,
            "partner_name": str(target.get("partner_name") or ""),
            "analytic_account_id": int(target.get("analytic_account_id") or 0) or None,
            "analytic_account_name": str(target.get("analytic_account_name") or ""),
        }
        if not clean_target["account_id"]:
            raise HTTPException(status_code=422, detail="A counterpart Odoo account is required.")
        version_number = self._next_version(db, rule.id)
        fingerprint = self._fingerprint(
            name=next_name,
            journal_id=rule.journal_id,
            company_id=rule.company_id,
            priority=next_priority,
            conditions=normalized_conditions,
            target=clean_target,
        )
        version = BankRuleVersion(
            bank_rule_id=rule.id,
            version_number=version_number,
            approval_status=DRAFT,
            conditions=normalized_conditions,
            target=clean_target,
            rationale=rationale.strip()[:4000] or None,
            change_note=change_note.strip()[:4000] or None,
            source_snapshot={"previous_name": rule.name, "previous_priority": rule.priority},
            fingerprint=fingerprint,
            created_by_user_id=user_id,
            created_at=_utc_now(),
        )
        db.add(version)
        db.flush()
        # Name/priority become executable only when this version is approved, so the
        # BankRule row is intentionally not mutated here.
        self._audit(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="bank_rule.version_drafted",
            entity_id=rule.id,
            details={"version_id": version.id, "version_number": version_number, "fingerprint": fingerprint},
        )
        db.commit()
        return self.serialize_rule(db, rule)

    def approve_version(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        rule_id: int,
        version_id: int,
        approval_note: str = "",
    ) -> dict[str, Any]:
        rule = self._rule(db, organization_id, rule_id)
        version = self._version(db, rule.id, version_id)
        if version.approval_status != DRAFT:
            raise HTTPException(status_code=409, detail="Only draft Bank Rule versions can be approved.")
        try:
            normalized_conditions = validate_conditions(list(version.conditions or []))
        except BankRuleDefinitionError as exc:
            raise HTTPException(status_code=422, detail=f"Rule cannot be activated: {exc}") from exc
        source_snapshot = dict(version.source_snapshot or {})
        if source_snapshot.get("import_requires_manual_configuration"):
            raise HTTPException(
                status_code=422,
                detail="Imported rule contains Odoo conditions that require manual mapping before activation.",
            )

        _connection, erp = self._erp_resolver.resolve(db, organization_id)
        journal = self._references.bank_journal(erp, rule.journal_id, rule.company_id)
        target = self._references.target_snapshot(erp, dict(version.target or {}))
        version.conditions = normalized_conditions
        version.target = target
        version.fingerprint = self._fingerprint(
            name=rule.name,
            journal_id=rule.journal_id,
            company_id=rule.company_id,
            priority=rule.priority,
            conditions=normalized_conditions,
            target=target,
        )
        previous = (
            db.query(BankRuleVersion)
            .filter(
                BankRuleVersion.bank_rule_id == rule.id,
                BankRuleVersion.approval_status == APPROVED,
            )
            .all()
        )
        for old in previous:
            old.approval_status = SUPERSEDED
        version.approval_status = APPROVED
        version.approved_by_user_id = user_id
        version.approved_at = _utc_now()
        rule.is_enabled = True
        # Draft edits can carry a proposed executable name/priority inside source_snapshot.
        proposed_name = source_snapshot.get("proposed_name")
        proposed_priority = source_snapshot.get("proposed_priority")
        if proposed_name:
            rule.name = str(proposed_name)[:200]
        if proposed_priority is not None:
            rule.priority = int(proposed_priority)
        self._audit(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="bank_rule.version_approved",
            entity_id=rule.id,
            details={
                "version_id": version.id,
                "version_number": version.version_number,
                "fingerprint": version.fingerprint,
                "journal_id": rule.journal_id,
                "journal_name": journal.get("journal_name"),
                "target_account_id": target.get("account_id"),
                "target_account_code": target.get("account_code"),
                "approval_note": approval_note.strip()[:2000],
            },
        )
        db.commit()
        return self.serialize_rule(db, rule)

    def disable_rule(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        rule_id: int,
        reason: str = "",
    ) -> dict[str, Any]:
        rule = self._rule(db, organization_id, rule_id)
        rule.is_enabled = False
        rule.retired_by_user_id = user_id
        rule.retired_at = _utc_now()
        self._audit(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="bank_rule.disabled",
            entity_id=rule.id,
            details={"reason": reason.strip()[:2000]},
        )
        db.commit()
        return self.serialize_rule(db, rule)

    def active_rules(
        self,
        db: Session,
        *,
        organization_id: int,
        journal_id: int,
        company_id: int | None,
    ) -> list[dict[str, Any]]:
        query = db.query(BankRule).filter(
            BankRule.organization_id == organization_id,
            BankRule.journal_id == journal_id,
            BankRule.is_enabled.is_(True),
        )
        if company_id is not None:
            query = query.filter((BankRule.company_id == company_id) | (BankRule.company_id.is_(None)))
        rows = query.order_by(BankRule.priority.asc(), BankRule.id.asc()).all()
        result: list[dict[str, Any]] = []
        for rule in rows:
            version = self._latest_version(db, rule.id, APPROVED)
            if not version:
                continue
            result.append({
                "rule_id": rule.id,
                "version_id": version.id,
                "version_number": version.version_number,
                "name": rule.name,
                "journal_id": rule.journal_id,
                "company_id": rule.company_id,
                "priority": rule.priority,
                "conditions": version.conditions or [],
                "target": version.target or {},
                "fingerprint": version.fingerprint,
                "source_system": rule.source_system,
                "source_external_id": rule.source_external_id,
            })
        return result

    @staticmethod
    def _odoo_conditions(rule: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        conditions: list[dict[str, Any]] = []
        warnings: list[str] = []
        label_mode = str(rule.get("match_label") or "").strip().lower()
        label_value = str(rule.get("match_label_param") or "").strip()
        operator_map = {
            "contains": "contains",
            "not_contains": "not_contains",
            "match_regex": "regex",
        }
        if label_value:
            mapped = operator_map.get(label_mode)
            if mapped:
                conditions.append({"field": "statement_text", "operator": mapped, "value": label_value})
            else:
                warnings.append(f"Unsupported Odoo label operator: {label_mode or 'missing'}")

        amount_mode = str(rule.get("match_amount") or "").strip().lower()
        minimum = rule.get("match_amount_min")
        maximum = rule.get("match_amount_max")
        if amount_mode == "lower":
            conditions.append({"field": "amount", "operator": "lte", "value": str(maximum)})
        elif amount_mode == "greater":
            conditions.append({"field": "amount", "operator": "gte", "value": str(minimum)})
        elif amount_mode == "between":
            conditions.append({"field": "amount", "operator": "between", "min": str(minimum), "max": str(maximum)})
        elif amount_mode:
            warnings.append(f"Unsupported Odoo amount mode: {amount_mode}")

        if rule.get("match_partner_ids"):
            warnings.append("Odoo partner restriction requires manual mapping in BOB")
        try:
            return validate_conditions(conditions), warnings
        except BankRuleDefinitionError:
            return conditions, warnings

    def import_from_odoo(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        journal_id: int,
        company_id: int | None,
    ) -> dict[str, Any]:
        _connection, erp = self._erp_resolver.resolve(db, organization_id)
        journal = self._references.bank_journal(erp, journal_id, company_id)
        effective_company_id = int(journal.get("company_id") or 0) or company_id
        odoo_rules = fetch_odoo_bank_rules(
            erp,
            company_id=effective_company_id,
            bank_journal_id=journal_id,
            limit=500,
        )
        imported: list[int] = []
        skipped: list[dict[str, Any]] = []
        for odoo_rule in odoo_rules:
            external_id = str(odoo_rule.get("id") or "")
            if not external_id:
                continue
            existing = (
                db.query(BankRule)
                .filter(
                    BankRule.organization_id == organization_id,
                    BankRule.journal_id == journal_id,
                    BankRule.source_system == "odoo_import",
                    BankRule.source_external_id == external_id,
                )
                .first()
            )
            if existing:
                skipped.append({"odoo_rule_id": external_id, "reason": "already_imported"})
                continue
            account_lines = []
            for line in odoo_rule.get("lines") or []:
                account_id, account_name = _m2o(line.get("account_id"))
                if account_id:
                    account_lines.append((line, account_id, account_name))
            if len(account_lines) != 1:
                skipped.append({
                    "odoo_rule_id": external_id,
                    "name": odoo_rule.get("name"),
                    "reason": "requires_exactly_one_counterpart_account",
                })
                continue
            line, account_id, account_name = account_lines[0]
            conditions, warnings = self._odoo_conditions(odoo_rule)
            partner_id, partner_name = _m2o(line.get("partner_id"))
            target = {
                "account_id": account_id,
                "account_name": account_name,
                "account_code": "",
                "partner_id": partner_id,
                "partner_name": partner_name,
                "analytic_account_id": None,
                "analytic_account_name": "",
            }
            source_snapshot = {
                "odoo_rule": odoo_rule,
                "import_warnings": warnings,
                "import_requires_manual_configuration": bool(warnings or not conditions),
            }
            try:
                created = self.create_rule(
                    db,
                    organization_id=organization_id,
                    user_id=user_id,
                    name=str(odoo_rule.get("name") or f"Odoo Rule {external_id}")[:200],
                    journal_id=journal_id,
                    company_id=effective_company_id,
                    priority=int(odoo_rule.get("sequence") or 100),
                    conditions=conditions,
                    target=target,
                    rationale="Imported from Odoo reconciliation model for one-time BOB migration.",
                    change_note="Imported as draft; explicit approval is required before BOB uses this rule.",
                    source_system="odoo_import",
                    source_external_id=external_id,
                    source_snapshot=source_snapshot,
                    validate_definition=False,
                )
                imported.append(int(created["id"]))
            except HTTPException as exc:
                skipped.append({
                    "odoo_rule_id": external_id,
                    "name": odoo_rule.get("name"),
                    "reason": str(exc.detail),
                })
        self._audit(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="bank_rules.odoo_import_completed",
            entity_id=None,
            details={
                "journal_id": journal_id,
                "company_id": effective_company_id,
                "source_rule_count": len(odoo_rules),
                "imported_count": len(imported),
                "skipped_count": len(skipped),
            },
        )
        db.commit()
        return {
            "status": "imported_as_drafts",
            "journal_id": journal_id,
            "company_id": effective_company_id,
            "source_rule_count": len(odoo_rules),
            "imported_count": len(imported),
            "imported_rule_ids": imported,
            "skipped_count": len(skipped),
            "skipped": skipped,
            "automatic_activation": False,
        }

    def test_rule(
        self,
        db: Session,
        *,
        organization_id: int,
        rule_id: int,
        transactions: Iterable[Any],
        max_samples: int = 25,
    ) -> dict[str, Any]:
        rule = self._rule(db, organization_id, rule_id)
        version = self._latest_version(db, rule.id, DRAFT) or self._latest_version(db, rule.id, APPROVED)
        if not version:
            raise HTTPException(status_code=422, detail="Bank Rule has no testable version.")
        try:
            conditions = validate_conditions(list(version.conditions or []))
        except BankRuleDefinitionError as exc:
            raise HTTPException(status_code=422, detail=f"Rule cannot be tested: {exc}") from exc
        candidate = {
            "rule_id": rule.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "name": rule.name,
            "priority": rule.priority,
            "conditions": conditions,
            "target": version.target or {},
            "fingerprint": version.fingerprint,
        }
        matched: list[dict[str, Any]] = []
        total = 0
        for transaction in transactions:
            total += 1
            payload = transaction.model_dump() if hasattr(transaction, "model_dump") else dict(transaction)
            resolution = bank_rules_engine.resolve(payload, [candidate])
            if resolution and resolution.get("suggested_account_id"):
                if len(matched) < max_samples:
                    matched.append({
                        "row_number": payload.get("row_number"),
                        "date": payload.get("date"),
                        "description": payload.get("description"),
                        "amount": str(payload.get("amount")),
                    })
        return {
            "rule_id": rule.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "tested_transaction_count": total,
            "matched_transaction_count": len(matched) if total <= max_samples else None,
            "sample_matches": matched,
            "note": "Test mode never mutates entries, rules, or Odoo.",
        }


bank_rules_service = BankRulesService()
