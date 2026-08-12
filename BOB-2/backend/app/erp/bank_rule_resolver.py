"""Resolve bank transactions only against Odoo reconciliation models.

Stage 1 reproduces explicit Odoo rule conditions deterministically. Stage 2 is a
review-only constrained suggestion among the same Odoo rules; it may help the
accountant classify manual/generic reconciliation models, but it can never become
posting-ready without human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.erp.bank_rule_suggestions import suggest_by_bank_rule
from app.erp.strict_bank_rule_matcher import match_by_odoo_bank_rule_strict


def _transaction_match_text(txn: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "description",
        "main_description",
        "transaction_details",
        "note",
        "memo",
        "reference",
        "payment_ref",
    ):
        value = txn.get(key)
        if value:
            values.append(str(value))
    details = txn.get("details")
    if isinstance(details, list):
        values.extend(str(value) for value in details if value)
    elif details:
        values.append(str(details))

    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            deduplicated.append(normalized)
    return " | ".join(deduplicated)


@dataclass(frozen=True, slots=True)
class OdooBankRuleResolver:
    """Strict first, then review-only suggestion constrained to Odoo rules."""

    review_confidence_ceiling: float = 0.69

    def resolve(
        self,
        txn: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        enriched = dict(txn)
        match_text = _transaction_match_text(enriched)
        if match_text:
            enriched["match_text"] = match_text
            # The legacy suggestion engine already considers this field. Supplying
            # the composite Odoo-equivalent text here avoids inventing new evidence.
            enriched["suggested_action_label"] = match_text

        strict = match_by_odoo_bank_rule_strict(enriched, rules)
        if strict:
            strict = dict(strict)
            strict["resolution_mode"] = "strict_odoo_condition"
            strict["needs_review"] = bool(strict.get("needs_review"))
            return strict

        suggestion = suggest_by_bank_rule(enriched, rules)
        if not suggestion or not suggestion.get("suggested_account_id") or not suggestion.get("bank_rule_id"):
            return None

        suggestion = dict(suggestion)
        raw_confidence = float(suggestion.get("confidence") or 0.0)
        suggestion["confidence"] = round(min(raw_confidence, self.review_confidence_ceiling), 4)
        suggestion["needs_review"] = True
        suggestion["resolution_mode"] = "review_only_odoo_rule_suggestion"
        suggestion["source_priority"] = "bank_rule_review_suggestion"
        suggestion["reason"] = (
            "No explicit Odoo reconciliation-model condition matched. "
            f"Review-only candidate {suggestion.get('bank_rule_name') or suggestion.get('bank_rule_id')} "
            "was selected only from Odoo Bank Rules using their configured names, labels, accounts, "
            "and statement evidence. Human confirmation is mandatory."
        )
        return suggestion


odoo_bank_rule_resolver = OdooBankRuleResolver()


def resolve_by_odoo_bank_rule(
    txn: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    return odoo_bank_rule_resolver.resolve(txn, rules)
