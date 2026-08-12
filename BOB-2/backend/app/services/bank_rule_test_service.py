"""Non-mutating test runner for BOB Bank Rule drafts/approved versions."""

from __future__ import annotations

from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.bank_rules import BankRule, BankRuleVersion
from app.services.bank_rules_engine import BankRuleDefinitionError, bank_rules_engine, validate_conditions


class BankRuleTestService:
    def test(
        self,
        db: Session,
        *,
        organization_id: int,
        rule_id: int,
        transactions: Iterable[Any],
        max_samples: int = 25,
    ) -> dict[str, Any]:
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
                BankRuleVersion.bank_rule_id == rule.id,
                BankRuleVersion.approval_status == "draft",
            )
            .order_by(BankRuleVersion.version_number.desc())
            .first()
        )
        if version is None:
            version = (
                db.query(BankRuleVersion)
                .filter(
                    BankRuleVersion.bank_rule_id == rule.id,
                    BankRuleVersion.approval_status == "approved",
                )
                .order_by(BankRuleVersion.version_number.desc())
                .first()
            )
        if version is None:
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

        tested_count = 0
        matched_count = 0
        samples: list[dict[str, Any]] = []
        for transaction in transactions:
            tested_count += 1
            payload = transaction.model_dump() if hasattr(transaction, "model_dump") else dict(transaction)
            resolution = bank_rules_engine.resolve(payload, [candidate])
            if not resolution or not resolution.get("suggested_account_id"):
                continue
            matched_count += 1
            if len(samples) < max_samples:
                samples.append({
                    "row_number": payload.get("row_number"),
                    "date": payload.get("date"),
                    "description": payload.get("description"),
                    "amount": str(payload.get("amount")),
                })

        return {
            "rule_id": rule.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "tested_transaction_count": tested_count,
            "matched_transaction_count": matched_count,
            "sample_match_count": len(samples),
            "sample_matches": samples,
            "note": "Test mode is read-only: it does not mutate the rule, statement, journal entries, or Odoo.",
        }


bank_rule_test_service = BankRuleTestService()
