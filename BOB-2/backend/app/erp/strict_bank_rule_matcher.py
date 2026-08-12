"""Fail-closed Odoo reconciliation-model matcher.

The implementation mirrors the observable Odoo 19 reconciliation model conditions:
journal scoping is applied by the loader, while label, amount and partner conditions are
checked here. No fuzzy inference is used in this strict stage.
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


def _m2m_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    ids: list[int] = []
    for item in value:
        if isinstance(item, int):
            ids.append(item)
        elif isinstance(item, (list, tuple)) and item:
            try:
                ids.append(int(item[0]))
            except (TypeError, ValueError):
                continue
    return ids


def _first_counterpart_line(rule: dict[str, Any]) -> dict[str, Any] | None:
    """Accept only a single explicit account line in the automatic strict stage."""
    account_lines: list[dict[str, Any]] = []
    for line in rule.get("lines") or []:
        account_id, _ = _m2o(line.get("account_id"))
        if account_id:
            account_lines.append(line)
    if len(account_lines) != 1:
        return None
    return account_lines[0]


def _candidate_texts(txn: dict[str, Any]) -> list[str]:
    values: list[str] = []
    match_text = str(txn.get("match_text") or "").strip()
    if match_text:
        values.extend(part.strip() for part in match_text.split("|") if part.strip())
    for key in ("description", "main_description", "transaction_details", "note", "memo", "reference", "payment_ref"):
        value = txn.get(key)
        if value:
            values.append(str(value).strip())
    details = txn.get("details")
    if isinstance(details, list):
        values.extend(str(value).strip() for value in details if value)
    elif details:
        values.append(str(details).strip())

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _contains(text: str, pattern: str) -> bool:
    return pattern.casefold() in text.casefold()


def _regex(text: str, pattern: str) -> bool:
    try:
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    except re.error:
        return False


def _label_matches(texts: list[str], operator: Any, pattern: Any) -> tuple[bool, bool]:
    value = str(pattern or "").strip()
    mode = str(operator or "").strip().casefold()
    if not mode and not value:
        return True, False
    if not mode or not value:
        return False, True

    if mode == "contains":
        return any(_contains(text, value) for text in texts), True
    if mode == "not_contains":
        return all(not _contains(text, value) for text in texts), True
    if mode == "match_regex":
        return any(_regex(text, value) for text in texts), True
    return False, True


def _number(value: Any) -> float | None:
    if value is None or value is False or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _amount_matches(rule: dict[str, Any], amount: float) -> tuple[bool, bool]:
    """Mirror Odoo 19 match_amount: lower/max, greater/min, or between."""
    mode = str(rule.get("match_amount") or "").strip().casefold()
    minimum = _number(rule.get("match_amount_min"))
    maximum = _number(rule.get("match_amount_max"))
    magnitude = abs(float(amount or 0.0))

    if not mode:
        # Odoo 19 persists inactive amount parameters as 0.0. They are not an
        # active filter unless match_amount is selected. Only retain non-zero
        # bounds here for compatibility with older/custom Odoo versions that may
        # expose bounds without the selector field.
        legacy_minimum = minimum if minimum not in (None, 0.0) else None
        legacy_maximum = maximum if maximum not in (None, 0.0) else None
        if legacy_minimum is None and legacy_maximum is None:
            return True, False
        if legacy_minimum is not None and magnitude < abs(legacy_minimum):
            return False, True
        if legacy_maximum is not None and magnitude > abs(legacy_maximum):
            return False, True
        return True, True

    if mode == "lower":
        return maximum is not None and magnitude <= abs(maximum), True
    if mode == "greater":
        return minimum is not None and magnitude >= abs(minimum), True
    if mode == "between":
        if minimum is None or maximum is None:
            return False, True
        low, high = sorted((abs(minimum), abs(maximum)))
        return low <= magnitude <= high, True
    return False, True


def _partner_matches(rule: dict[str, Any], txn: dict[str, Any]) -> tuple[bool, bool]:
    allowed = _m2m_ids(rule.get("match_partner_ids"))
    if not allowed:
        return True, False
    partner_id, _ = _m2o(txn.get("partner_id"))
    if partner_id is None:
        raw = txn.get("partner_id")
        if isinstance(raw, int):
            partner_id = raw
    return bool(partner_id and partner_id in allowed), True


def match_by_odoo_bank_rule_strict(
    txn: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    texts = _candidate_texts(txn)
    if not texts:
        return None
    description = str(txn.get("description") or texts[0]).strip()
    amount = float(txn.get("amount") or 0.0)

    for rule in rules:
        line = _first_counterpart_line(rule)
        if not line:
            continue

        label_ok, has_label_condition = _label_matches(
            texts,
            rule.get("match_label"),
            rule.get("match_label_param"),
        )
        if not label_ok:
            continue

        amount_ok, has_amount_condition = _amount_matches(rule, amount)
        if not amount_ok:
            continue

        partner_ok, has_partner_condition = _partner_matches(rule, txn)
        if not partner_ok:
            continue

        # A manual catch-all rule without any observable condition is not safe to
        # auto-apply. It remains eligible for the review-only constrained stage.
        if not (has_label_condition or has_amount_condition or has_partner_condition):
            continue

        account_id, account_label = _m2o(line.get("account_id"))
        if not account_id:
            continue
        partner_id, partner_label = _m2o(line.get("partner_id"))

        evidence: list[str] = []
        if has_label_condition:
            evidence.append(f"label[{rule.get('match_label')}]={rule.get('match_label_param')}")
        if has_amount_condition:
            evidence.append(
                f"amount[{rule.get('match_amount') or 'bounds'}]={rule.get('match_amount_min') or '*'}..{rule.get('match_amount_max') or '*'}"
            )
        if has_partner_condition:
            evidence.append(f"partner_ids={_m2m_ids(rule.get('match_partner_ids'))}")

        return {
            "row_number": txn.get("row_number"),
            "date": txn.get("date"),
            "description": description,
            "amount": txn.get("amount"),
            "suggested_account_id": account_id,
            "suggested_account_label": account_label,
            "suggested_partner_id": partner_id,
            "suggested_partner_label": partner_label,
            "suggested_analytic_account_id": None,
            "suggested_analytic_account_label": "",
            "confidence": 1.0,
            "source": "odoo_bank_reconciliation_rule",
            "source_priority": "bank_rule_strict",
            "bank_rule_id": rule.get("id"),
            "bank_rule_name": rule.get("name"),
            "reason": (
                f"Strictly matched Odoo Bank Rule {rule.get('name') or rule.get('id')} "
                f"using configured conditions ({'; '.join(evidence)})."
            ),
            "needs_review": False,
            "resolution_mode": "strict_odoo_condition",
        }

    return None
