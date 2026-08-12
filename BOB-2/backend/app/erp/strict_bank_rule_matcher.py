"""Fail-closed matcher for Odoo reconciliation rules used in posting candidates.

Unlike similarity suggestions, this matcher does not guess. A rule must have an explicit
statement-text, amount, or safely understood direction condition that the transaction
satisfies. Rules are evaluated in the Odoo sequence order returned by
``fetch_odoo_bank_rules``.
"""

from __future__ import annotations

import re
from typing import Any


def _m2o(value: Any) -> tuple[int | None, str]:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0]) if value[0] else None, str(value[1] if len(value) > 1 else "")
    if isinstance(value, int):
        return value, ""
    return None, ""


def _first_counterpart_line(rule: dict[str, Any]) -> dict[str, Any] | None:
    for line in rule.get("lines") or []:
        account_id, _ = _m2o(line.get("account_id"))
        if account_id:
            return line
    return None


def _plain_contains(text: str, pattern: str) -> bool:
    return pattern.casefold() in text.casefold()


def _safe_regex(text: str, pattern: str) -> bool:
    try:
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    except re.error:
        return False


def _text_condition_matches(text: str, operator: Any, pattern: Any) -> bool:
    value = str(pattern or "").strip()
    if not value:
        return True
    mode = str(operator or "").strip().casefold()
    if mode in {"contains", "contain"}:
        return _plain_contains(text, value)
    if mode in {"not_contains", "not contains", "not_contain"}:
        return not _plain_contains(text, value)
    if mode in {"match_regex", "regex", "matches_regex"}:
        return _safe_regex(text, value)
    if mode in {"equals", "equal", "exact"}:
        return text.strip().casefold() == value.casefold()
    if mode in {"starts_with", "starts with"}:
        return text.strip().casefold().startswith(value.casefold())
    if mode in {"ends_with", "ends with"}:
        return text.strip().casefold().endswith(value.casefold())
    # Missing/unknown Odoo operator is not interpreted heuristically for a posting
    # candidate. The transaction remains unresolved and visible to the reviewer.
    return False


def _number(value: Any) -> float | None:
    if value in (None, False, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _amount_matches(rule: dict[str, Any], amount: float) -> tuple[bool, bool]:
    magnitude = abs(float(amount or 0.0))
    minimum = _number(rule.get("match_amount_min"))
    maximum = _number(rule.get("match_amount_max"))
    has_condition = minimum is not None or maximum is not None
    if minimum is not None and magnitude < abs(minimum):
        return False, has_condition
    if maximum is not None and magnitude > abs(maximum):
        return False, has_condition
    return True, has_condition


def _transaction_type_matches(configured: str, amount: float) -> tuple[bool, bool]:
    value = configured.strip().casefold()
    if not value or value in {"all", "both", "all_transactions"}:
        return True, False
    incoming = {"incoming", "inbound", "received", "receipt", "credit", "positive"}
    outgoing = {"outgoing", "outbound", "sent", "payment", "debit", "negative"}
    if value in incoming:
        return amount > 0, True
    if value in outgoing:
        return amount < 0, True
    return False, True


def match_by_odoo_bank_rule_strict(
    txn: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    description = str(txn.get("description") or "").strip()
    if not description:
        return None
    amount = float(txn.get("amount") or 0.0)

    for rule in rules:
        line = _first_counterpart_line(rule)
        if not line:
            continue

        label_pattern = str(rule.get("match_label_param") or "").strip()
        note_pattern = str(rule.get("match_note_param") or "").strip()
        if label_pattern and not _text_condition_matches(description, rule.get("match_label"), label_pattern):
            continue
        if note_pattern and not _text_condition_matches(description, rule.get("match_note"), note_pattern):
            continue
        text_conditions = [value for value in (label_pattern, note_pattern) if value]

        amount_ok, has_amount_condition = _amount_matches(rule, amount)
        if not amount_ok:
            continue

        transaction_type = str(rule.get("match_transaction_type") or "").strip()
        transaction_type_ok, has_transaction_type_condition = _transaction_type_matches(transaction_type, amount)
        if not transaction_type_ok:
            continue

        has_explicit_condition = bool(
            text_conditions or has_amount_condition or has_transaction_type_condition
        )
        if not has_explicit_condition:
            continue

        account_id, account_label = _m2o(line.get("account_id"))
        if not account_id:
            continue
        partner_id, partner_label = _m2o(line.get("partner_id"))
        if not partner_id:
            partner_id, partner_label = _m2o(rule.get("partner_id"))
        analytic_id, analytic_label = _m2o(line.get("analytic_account_id"))
        confidence = 1.0 if text_conditions else 0.9
        evidence = []
        if label_pattern:
            evidence.append(f"label[{rule.get('match_label')}]={label_pattern}")
        if note_pattern:
            evidence.append(f"note[{rule.get('match_note')}]={note_pattern}")
        if has_amount_condition:
            evidence.append(
                f"amount_range={rule.get('match_amount_min') or '*'}..{rule.get('match_amount_max') or '*'}"
            )
        if has_transaction_type_condition:
            evidence.append(f"transaction_type={transaction_type}")

        return {
            "row_number": txn.get("row_number"),
            "date": txn.get("date"),
            "description": description,
            "amount": txn.get("amount"),
            "suggested_account_id": account_id,
            "suggested_account_label": account_label,
            "suggested_partner_id": partner_id,
            "suggested_partner_label": partner_label,
            "suggested_analytic_account_id": analytic_id,
            "suggested_analytic_account_label": analytic_label,
            "confidence": confidence,
            "source": "odoo_bank_reconciliation_rule",
            "source_priority": "bank_rule_strict",
            "bank_rule_id": rule.get("id"),
            "bank_rule_name": rule.get("name"),
            "reason": (
                f"Strictly matched Odoo Bank Rule {rule.get('name') or rule.get('id')} "
                f"using explicit configured conditions ({'; '.join(evidence)})."
            ),
            "needs_review": confidence < 0.70,
        }

    return None
