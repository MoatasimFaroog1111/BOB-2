from __future__ import annotations

import re
from difflib import SequenceMatcher
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
    out: list[int] = []
    for item in value:
        if isinstance(item, int):
            out.append(item)
        elif isinstance(item, (list, tuple)) and item:
            try:
                out.append(int(item[0]))
            except Exception:
                pass
    return out


def _norm(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", " ", text)
    text = re.sub(r"\b(ref|reference|txn|transaction|date|time|sar|vat|iban|swift|mada|visa|card|bank)\b", " ", text)
    text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: Any, b: Any) -> float:
    left = _norm(a)
    right = _norm(b)
    if not left or not right:
        return 0.0
    seq = SequenceMatcher(None, left, right).ratio()
    ta = {x for x in left.split() if len(x) > 2}
    tb = {x for x in right.split() if len(x) > 2}
    overlap = len(ta & tb) / max(len(ta | tb), 1)
    return max(seq, overlap)


def _category(text: Any) -> str:
    t = _norm(text)
    if re.search(r"رسوم|عموله|عمولة|fee|charge|commission", t):
        return "bank_fees"
    if re.search(r"راتب|رواتب|salary|payroll|wps", t):
        return "payroll"
    if re.search(r"ضريبه|ضريبة|زكاه|زكاة|vat|tax", t):
        return "tax"
    if re.search(r"سداد|sadad|bill|فاتوره|فاتورة|mol|government", t):
        return "bill_payment"
    if re.search(r"تحويل|transfer|instant payment", t):
        return "transfer"
    if re.search(r"pos|شبكه|شبكة|مدي|مدى|settlement", t):
        return "pos_settlement"
    return "general"


def _fields(erp: Any, model: str) -> set[str]:
    try:
        raw = erp.execute_kw(model, "fields_get", [], {"attributes": ["string"]})
        return set(raw.keys()) if isinstance(raw, dict) else set()
    except Exception:
        return set()


def _read(erp: Any, model: str, domain: list[Any], fields: list[str], limit: int, order: str = "id asc") -> list[dict[str, Any]]:
    available = _fields(erp, model)
    selected = [f for f in fields if not available or f in available]
    if not selected:
        selected = ["id", "name"]
    try:
        return erp.execute_kw(model, "search_read", [domain], {"fields": selected, "limit": limit, "order": order})
    except Exception:
        return []


def _rule_text(rule: dict[str, Any]) -> str:
    line_text = []
    for line in rule.get("lines") or []:
        _account_id, account_name = _m2o(line.get("account_id"))
        _partner_id, partner_name = _m2o(line.get("partner_id"))
        line_text.extend([str(line.get("label") or ""), str(line.get("name") or ""), account_name, partner_name])
    _partner_id, partner_name = _m2o(rule.get("partner_id"))
    return " ".join(filter(None, [
        str(rule.get("name") or ""),
        str(rule.get("rule_type") or ""),
        str(rule.get("match_label_param") or ""),
        str(rule.get("match_note_param") or ""),
        str(rule.get("match_transaction_type") or ""),
        partner_name,
        " ".join(line_text),
    ]))


def _amount_score(rule: dict[str, Any], amount: float) -> float:
    def num(v: Any) -> float | None:
        try:
            return None if v in (None, False, "") else float(str(v).replace(",", ""))
        except Exception:
            return None
    amt = abs(float(amount or 0.0))
    lo = num(rule.get("match_amount_min"))
    hi = num(rule.get("match_amount_max"))
    if lo is None and hi is None:
        return 0.45
    if lo is not None and amt < abs(lo):
        return 0.0
    if hi is not None and amt > abs(hi):
        return 0.0
    return 1.0


def _first_counterpart_line(rule: dict[str, Any]) -> dict[str, Any] | None:
    for line in rule.get("lines") or []:
        account_id, _ = _m2o(line.get("account_id"))
        if account_id:
            return line
    return None


def fetch_odoo_bank_rules(erp: Any, *, company_id: int | None, bank_journal_id: int | None, limit: int = 200) -> list[dict[str, Any]]:
    rule_fields = [
        "id", "name", "sequence", "active", "company_id", "rule_type", "match_journal_ids",
        "match_label_param", "match_note_param", "match_transaction_type", "match_amount_min", "match_amount_max", "partner_id",
    ]
    domain: list[Any] = [["active", "=", True]]
    if company_id:
        domain = [["active", "=", True], "|", ["company_id", "=", False], ["company_id", "=", int(company_id)]]
    rules = _read(erp, "account.reconcile.model", domain, rule_fields, max(20, min(limit, 500)), "sequence asc, id asc")
    if not rules:
        return []

    rule_ids = [int(r["id"]) for r in rules if r.get("id")]
    line_fields = ["id", "model_id", "account_id", "partner_id", "analytic_account_id", "label", "name", "amount_type", "amount_string"]
    lines = _read(erp, "account.reconcile.model.line", [["model_id", "in", rule_ids]], line_fields, min(max(len(rule_ids) * 8, 100), 2000), "id asc")
    by_rule: dict[int, list[dict[str, Any]]] = {}
    for line in lines:
        model_id, _ = _m2o(line.get("model_id"))
        if model_id:
            by_rule.setdefault(model_id, []).append(line)

    out: list[dict[str, Any]] = []
    for rule in rules:
        journals = _m2m_ids(rule.get("match_journal_ids"))
        if bank_journal_id and journals and int(bank_journal_id) not in journals:
            continue
        rid = int(rule.get("id") or 0)
        out.append({**rule, "lines": by_rule.get(rid, [])})
    return out


def suggest_by_bank_rule(txn: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    txn_text = " ".join(str(txn.get(k) or "") for k in ["description", "suggested_action_label", "explanation", "detected_category"])
    txn_category = _category(txn_text)
    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for rule in rules:
        line = _first_counterpart_line(rule)
        if not line:
            continue
        rule_text = _rule_text(rule)
        label_score = max(
            _similarity(txn_text, rule_text),
            1.0 if _norm(rule.get("match_label_param")) and _norm(rule.get("match_label_param")) in _norm(txn_text) else 0.0,
            1.0 if _norm(rule.get("match_note_param")) and _norm(rule.get("match_note_param")) in _norm(txn_text) else 0.0,
        )
        category_score = 1.0 if txn_category != "general" and txn_category == _category(rule_text) else 0.0
        score = min(label_score * 0.62 + category_score * 0.18 + _amount_score(rule, float(txn.get("amount") or 0.0)) * 0.20, 1.0)
        if best is None or score > best[0]:
            best = (score, rule, line)
    if not best or best[0] < 0.42:
        return None

    score, rule, line = best
    account_id, account_label = _m2o(line.get("account_id"))
    partner_id, partner_label = _m2o(line.get("partner_id"))
    if not partner_id:
        partner_id, partner_label = _m2o(rule.get("partner_id"))
    analytic_id, analytic_label = _m2o(line.get("analytic_account_id"))
    return {
        "row_number": txn.get("row_number"),
        "date": txn.get("date"),
        "description": txn.get("description"),
        "amount": txn.get("amount"),
        "suggested_account_id": account_id,
        "suggested_account_label": account_label,
        "suggested_partner_id": partner_id,
        "suggested_partner_label": partner_label,
        "suggested_analytic_account_id": analytic_id,
        "suggested_analytic_account_label": analytic_label,
        "confidence": round(score, 4),
        "source": "odoo_bank_reconciliation_rule",
        "source_priority": "bank_rule",
        "bank_rule_id": rule.get("id"),
        "bank_rule_name": rule.get("name"),
        "reason": f"Matched Odoo bank rule {rule.get('name') or rule.get('id')} and used its configured counterpart account data.",
        "needs_review": score < 0.70,
    }
