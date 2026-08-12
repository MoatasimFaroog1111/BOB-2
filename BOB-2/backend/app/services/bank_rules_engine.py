"""Deterministic Bank Rules Engine owned by BOB.

The engine is pure business logic: it receives bank transactions and approved/versioned
rules, evaluates explicit conditions, and returns an explainable resolution. It performs
no database, HTTP, ERP, or posting operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class BankRuleDefinitionError(ValueError):
    pass


_TEXT_OPERATORS = {
    "contains",
    "not_contains",
    "equals",
    "starts_with",
    "ends_with",
    "regex",
}
_AMOUNT_OPERATORS = {"equals", "gt", "gte", "lt", "lte", "between"}
_DIRECTION_VALUES = {"inflow", "outflow"}


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def transaction_statement_text(transaction: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "description",
        "main_description",
        "reference",
        "payment_ref",
        "note",
        "memo",
    ):
        value = transaction.get(key)
        if value:
            values.append(_normalized_text(value))
    details = transaction.get("details")
    if isinstance(details, list):
        values.extend(_normalized_text(item) for item in details if item)
    elif details:
        values.append(_normalized_text(details))

    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        folded = value.casefold()
        if value and folded not in seen:
            seen.add(folded)
            unique.append(value)
    return " | ".join(unique)


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BankRuleDefinitionError(f"Invalid decimal for {field}") from exc


def _validate_regex(pattern: str) -> re.Pattern[str]:
    if not pattern or len(pattern) > 256:
        raise BankRuleDefinitionError("Regex pattern must contain 1-256 characters")
    # Deliberately reject constructs that are difficult to bound or audit. BOB Bank
    # Rules are classification controls, not a general-purpose regex execution API.
    forbidden = ("(?=", "(?!", "(?<=", "(?<!", "(?P", "\\1", "\\2", "\\3")
    if any(token in pattern for token in forbidden):
        raise BankRuleDefinitionError(
            "Regex lookarounds, groups with references, and backreferences are not allowed"
        )
    if re.search(r"(?:\*|\+|\{\d+,?\d*\})\s*[+*{]", pattern):
        raise BankRuleDefinitionError("Nested/repeated regex quantifiers are not allowed")
    # Reject a quantified group that already contains a quantified expression, e.g.
    # (a+)+ or (ab*){2,}. This is a common catastrophic-backtracking shape and is not
    # needed for deterministic bank classification rules.
    if re.search(r"\([^()]*[+*{][^()]*\)\s*(?:[+*]|\{)", pattern):
        raise BankRuleDefinitionError("Nested quantified regex groups are not allowed")
    try:
        return re.compile(pattern, flags=re.IGNORECASE)
    except re.error as exc:
        raise BankRuleDefinitionError("Invalid regex pattern") from exc


def _safe_regex_match(text: str, pattern: str) -> bool:
    return _validate_regex(pattern).search(text[:4096]) is not None


def validate_conditions(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(conditions, list) or not conditions:
        raise BankRuleDefinitionError("At least one explicit Bank Rule condition is required")
    if len(conditions) > 12:
        raise BankRuleDefinitionError("A Bank Rule may contain at most 12 conditions")

    normalized: list[dict[str, Any]] = []
    for raw in conditions:
        if not isinstance(raw, dict):
            raise BankRuleDefinitionError("Every Bank Rule condition must be an object")
        field = str(raw.get("field") or "").strip().lower()
        operator = str(raw.get("operator") or "").strip().lower()
        if field == "statement_text":
            if operator not in _TEXT_OPERATORS:
                raise BankRuleDefinitionError(f"Unsupported statement_text operator: {operator}")
            value = _normalized_text(raw.get("value"))
            if not value:
                raise BankRuleDefinitionError("statement_text condition requires a value")
            if operator == "regex":
                _validate_regex(value)
            normalized.append({"field": field, "operator": operator, "value": value})
            continue
        if field == "amount":
            if operator not in _AMOUNT_OPERATORS:
                raise BankRuleDefinitionError(f"Unsupported amount operator: {operator}")
            if operator == "between":
                minimum = _decimal(raw.get("min"), field="amount.min")
                maximum = _decimal(raw.get("max"), field="amount.max")
                if minimum > maximum:
                    raise BankRuleDefinitionError("amount.min cannot be greater than amount.max")
                normalized.append({
                    "field": field,
                    "operator": operator,
                    "min": str(minimum),
                    "max": str(maximum),
                })
            else:
                value = _decimal(raw.get("value"), field="amount.value")
                normalized.append({"field": field, "operator": operator, "value": str(value)})
            continue
        if field == "direction":
            if operator != "equals":
                raise BankRuleDefinitionError("direction only supports the equals operator")
            value = str(raw.get("value") or "").strip().lower()
            if value not in _DIRECTION_VALUES:
                raise BankRuleDefinitionError("direction must be inflow or outflow")
            normalized.append({"field": field, "operator": operator, "value": value})
            continue
        raise BankRuleDefinitionError(f"Unsupported Bank Rule field: {field}")
    return normalized


def _condition_matches(transaction: Mapping[str, Any], condition: Mapping[str, Any]) -> bool:
    field = str(condition["field"])
    operator = str(condition["operator"])
    if field == "statement_text":
        text = transaction_statement_text(transaction)
        value = str(condition["value"])
        left = text.casefold()
        right = value.casefold()
        if operator == "contains":
            return right in left
        if operator == "not_contains":
            return right not in left
        if operator == "equals":
            return left == right
        if operator == "starts_with":
            return left.startswith(right)
        if operator == "ends_with":
            return left.endswith(right)
        if operator == "regex":
            return _safe_regex_match(text, value)
        return False

    amount = _decimal(transaction.get("amount"), field="transaction.amount")
    if field == "direction":
        direction = "inflow" if amount > 0 else "outflow" if amount < 0 else "zero"
        return direction == str(condition["value"])
    if field == "amount":
        magnitude = abs(amount)
        if operator == "between":
            return _decimal(condition["min"], field="condition.min") <= magnitude <= _decimal(
                condition["max"], field="condition.max"
            )
        target = abs(_decimal(condition["value"], field="condition.value"))
        if operator == "equals":
            return magnitude == target
        if operator == "gt":
            return magnitude > target
        if operator == "gte":
            return magnitude >= target
        if operator == "lt":
            return magnitude < target
        if operator == "lte":
            return magnitude <= target
    return False


def rule_matches(transaction: Mapping[str, Any], rule: Mapping[str, Any]) -> bool:
    conditions = validate_conditions(list(rule.get("conditions") or []))
    return all(_condition_matches(transaction, condition) for condition in conditions)


@dataclass(frozen=True, slots=True)
class BankRulesEngine:
    """Resolve a transaction against approved BOB rules using deterministic priority."""

    def resolve(
        self,
        transaction: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for raw_rule in rules:
            try:
                if rule_matches(transaction, raw_rule):
                    matches.append(raw_rule)
            except BankRuleDefinitionError:
                # Active rule definitions are validated before activation. If corrupted
                # storage is ever encountered, fail closed by not applying the rule.
                continue
        if not matches:
            return None

        matches.sort(key=lambda item: (int(item.get("priority") or 100), int(item.get("rule_id") or 0)))
        best_priority = int(matches[0].get("priority") or 100)
        best = [item for item in matches if int(item.get("priority") or 100) == best_priority]
        if len(best) != 1:
            return {
                "ambiguous": True,
                "confidence": 0.0,
                "needs_review": True,
                "source": "bob_bank_rule",
                "source_priority": "ambiguous_same_priority",
                "resolution_mode": "ambiguous_bob_rules",
                "reason": (
                    "Multiple active BOB Bank Rules matched at the same priority. "
                    "No account was selected; adjust priorities or conditions."
                ),
                "candidate_rule_ids": [int(item.get("rule_id") or 0) for item in best],
            }

        rule = best[0]
        target = dict(rule.get("target") or {})
        account_id = int(target.get("account_id") or 0)
        if account_id <= 0:
            return None
        return {
            "suggested_account_id": account_id,
            "suggested_account_label": str(target.get("account_name") or ""),
            "suggested_partner_id": int(target.get("partner_id") or 0) or None,
            "suggested_partner_label": str(target.get("partner_name") or ""),
            "suggested_analytic_account_id": int(target.get("analytic_account_id") or 0) or None,
            "suggested_analytic_account_label": str(target.get("analytic_account_name") or ""),
            "confidence": 1.0,
            "source": "bob_bank_rule",
            "source_priority": "bob_rule_priority",
            "resolution_mode": "strict_bob_rule",
            "bank_rule_id": int(rule["rule_id"]),
            "bank_rule_version_id": int(rule["version_id"]),
            "bank_rule_version": int(rule["version_number"]),
            "bank_rule_fingerprint": str(rule.get("fingerprint") or ""),
            "bank_rule_name": str(rule.get("name") or ""),
            "reason": (
                f"Matched active BOB Bank Rule {rule.get('name') or rule.get('rule_id')} "
                f"version {rule.get('version_number')} at priority {best_priority} using all configured conditions."
            ),
            "needs_review": False,
        }


bank_rules_engine = BankRulesEngine()


def resolve_by_bob_bank_rule(
    transaction: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    return bank_rules_engine.resolve(transaction, rules)
