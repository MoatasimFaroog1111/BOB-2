"""Read-only Bank Rule context for the Smart Accountant assistant."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.bank_rules import BankRule, BankRuleVersion


class BankRuleAssistantContextProvider:
    """Expose only executable approved rules; drafts never enter LLM context."""

    def load(
        self,
        db: Session,
        *,
        organization_id: int,
        journal_id: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = db.query(BankRule).filter(
            BankRule.organization_id == organization_id,
            BankRule.is_enabled.is_(True),
        )
        if journal_id:
            query = query.filter(BankRule.journal_id == journal_id)
        rules = query.order_by(BankRule.priority.asc(), BankRule.id.asc()).limit(min(max(limit, 1), 500)).all()
        result: list[dict[str, Any]] = []
        for rule in rules:
            version = (
                db.query(BankRuleVersion)
                .filter(
                    BankRuleVersion.bank_rule_id == rule.id,
                    BankRuleVersion.approval_status == "approved",
                )
                .order_by(BankRuleVersion.version_number.desc())
                .first()
            )
            if not version:
                continue
            result.append({
                "rule_id": rule.id,
                "name": rule.name,
                "journal_id": rule.journal_id,
                "company_id": rule.company_id,
                "priority": rule.priority,
                "version_id": version.id,
                "version_number": version.version_number,
                "fingerprint": version.fingerprint,
                "conditions": version.conditions or [],
                "target": version.target or {},
            })
        return result

    @staticmethod
    def format_for_llm(rules: list[dict[str, Any]]) -> str:
        if not rules:
            return "No approved active BOB Bank Rules are configured. Do not infer or invent a rule/account."
        lines: list[str] = []
        for rule in rules:
            target = rule.get("target") or {}
            conditions = rule.get("conditions") or []
            rendered_conditions = " AND ".join(
                (
                    f"{condition.get('field')} {condition.get('operator')} "
                    f"{condition.get('value') if condition.get('operator') != 'between' else str(condition.get('min')) + '..' + str(condition.get('max'))}"
                )
                for condition in conditions
            )
            lines.append(
                "- "
                f"RuleID={rule.get('rule_id')}, Version={rule.get('version_number')}, "
                f"Name=\"{rule.get('name')}\", JournalID={rule.get('journal_id')}, Priority={rule.get('priority')}, "
                f"Conditions=[{rendered_conditions}] -> "
                f"AccountID={target.get('account_id')}, AccountCode={target.get('account_code')}, "
                f"AccountName=\"{target.get('account_name')}\", Partner=\"{target.get('partner_name') or ''}\", "
                f"Analytic=\"{target.get('analytic_account_name') or ''}\", Fingerprint={rule.get('fingerprint')}"
            )
        return "\n".join(lines)


bank_rule_assistant_context_provider = BankRuleAssistantContextProvider()
