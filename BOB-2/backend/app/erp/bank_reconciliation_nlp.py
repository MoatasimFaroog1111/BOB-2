"""Deterministic NLP suggestions for bank reconciliation exceptions.

This module is intentionally local and explainable. It does not call an LLM,
does not require Vector DB availability, and never posts to Odoo.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670]")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u0600-\u06FF]+")
IBAN_RE = re.compile(r"\bSA\d{22}\b", re.IGNORECASE)
REF_RE = re.compile(r"\b(?:REF|FT|TRN|TXN|INV|PO|BILL|SADAD)[\s:#-]*([A-Z0-9-]{4,})\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d{5,}\b")

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "bank_charge": ["رسوم", "رسم", "عمولة", "مصرفية", "fee", "fees", "charge", "charges", "commission", "bank charge", "service charge"],
    "internal_transfer": ["تحويل داخلي", "بين حساباتي", "internal transfer", "own account", "transfer between", "liquidity transfer"],
    "payroll": ["راتب", "رواتب", "مسير", "اجور", "أجور", "salary", "payroll", "wage", "wages", "gosi payroll", "wps"],
    "supplier_payment": ["مورد", "supplier", "vendor", "payment to", "فاتورة مورد", "vendor bill", "invoice payment"],
    "customer_receipt": ["ايداع", "إيداع", "تحصيل", "قبض", "customer", "receipt", "collection", "deposit", "incoming transfer"],
    "sadad_government_payment": ["سداد", "حكومي", "وزارة", "الجوازات", "مقيم", "مكتب العمل", "زكاة", "ضريبة", "جمارك", "sadad", "government", "moi", "mol", "gosi", "zatca", "customs"],
    "atm_withdrawal": ["صراف", "سحب نقدي", "atm", "cash withdrawal", "withdrawal"],
    "card_pos": ["مدى", "نقاط بيع", "بطاقة", "pos", "mada", "card", "visa", "mastercard"],
    "loan_payment": ["قرض", "تمويل", "قسط", "loan", "finance", "installment", "murabaha"],
    "vat_tax": ["ضريبة", "القيمة المضافة", "vat", "tax", "zatca"],
}

ACTION_LABELS: dict[str, dict[str, str]] = {
    "bank_charge": {"en": "Review as bank charge", "ar": "مراجعة كرسوم بنكية"},
    "internal_transfer": {"en": "Review as internal transfer", "ar": "مراجعة كتحويل داخلي"},
    "payroll": {"en": "Review against payroll batch", "ar": "مراجعة مقابل مسير الرواتب"},
    "supplier_payment": {"en": "Review as supplier payment", "ar": "مراجعة كدفعة مورد"},
    "customer_receipt": {"en": "Review as customer receipt", "ar": "مراجعة كمقبوضات عميل"},
    "sadad_government_payment": {"en": "Review as SADAD/government payment", "ar": "مراجعة كدفعة سداد/حكومية"},
    "atm_withdrawal": {"en": "Review as ATM cash withdrawal", "ar": "مراجعة كسحب نقدي من صراف"},
    "card_pos": {"en": "Review as card/POS transaction", "ar": "مراجعة كعملية بطاقة/نقاط بيع"},
    "loan_payment": {"en": "Review as financing/loan payment", "ar": "مراجعة كقسط تمويل/قرض"},
    "vat_tax": {"en": "Review as VAT/tax payment", "ar": "مراجعة كضريبة/زكاة"},
    "posting_date_mismatch": {"en": "Check posting date mismatch", "ar": "تحقق من اختلاف تاريخ الترحيل"},
    "missing_odoo_entry": {"en": "Create draft journal-entry preview only", "ar": "إنشاء معاينة قيد فقط للمراجعة"},
    "missing_bank_line": {"en": "Check missing bank line", "ar": "تحقق من سطر البنك المفقود"},
    "duplicate_possible": {"en": "Check possible duplicate", "ar": "تحقق من احتمال التكرار"},
    "needs_review": {"en": "Needs manual review", "ar": "يحتاج مراجعة يدوية"},
}


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = ARABIC_DIACRITICS.sub("", value)
    value = value.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }))
    value = re.sub(r"[^\w\s\u0600-\u06FF:/#.-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize_text(text))


def extract_entities(text: str) -> dict[str, list[str]]:
    normalized = normalize_text(text).upper()
    ibans = sorted(set(IBAN_RE.findall(normalized)))
    refs = sorted(set(match.group(1) for match in REF_RE.finditer(normalized)))
    long_numbers = sorted(set(NUMBER_RE.findall(normalized)))[:10]
    return {"ibans": ibans, "references": refs, "numbers": long_numbers}


def _keyword_hits(normalized_text: str, category: str) -> list[str]:
    hits: list[str] = []
    for keyword in CATEGORY_KEYWORDS.get(category, []):
        if normalize_text(keyword) in normalized_text:
            hits.append(keyword)
    return hits


def _best_category(description: str, amount: float) -> tuple[str, list[str], float]:
    normalized = normalize_text(description)
    scored: list[tuple[str, list[str], float]] = []
    for category in CATEGORY_KEYWORDS:
        hits = _keyword_hits(normalized, category)
        if not hits:
            continue
        score = 0.58 + min(len(hits), 4) * 0.08
        if category in {"bank_charge", "payroll", "sadad_government_payment"}:
            score += 0.06
        if amount < 0 and category in {"bank_charge", "supplier_payment", "sadad_government_payment", "atm_withdrawal", "loan_payment", "vat_tax"}:
            score += 0.04
        if amount > 0 and category == "customer_receipt":
            score += 0.06
        scored.append((category, hits, min(score, 0.95)))
    if not scored:
        return "needs_review", [], 0.35
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored[0]


def _duplicate_signal(description: str, peers: list[dict[str, Any]] | None) -> float:
    if not peers:
        return 0.0
    normalized = normalize_text(description)
    best = 0.0
    for peer in peers:
        other = normalize_text(str(peer.get("description", "")))
        if not other or other == normalized:
            continue
        best = max(best, SequenceMatcher(None, normalized, other).ratio())
    return best


def suggest_transaction_action(
    transaction: Any,
    side: str,
    peers: list[dict[str, Any]] | None = None,
    language: str = "en",
) -> dict[str, Any]:
    """Return an explainable, non-posting suggestion for one exception row."""
    description = str(getattr(transaction, "description", None) or transaction.get("description", "") if isinstance(transaction, dict) else "")
    amount = float(getattr(transaction, "amount", None) if not isinstance(transaction, dict) else transaction.get("amount", 0) or 0)
    row_number = getattr(transaction, "row_number", None) if not isinstance(transaction, dict) else transaction.get("row_number")
    normalized = normalize_text(description)
    tokens = tokenize(description)
    entities = extract_entities(description)
    category, hits, confidence = _best_category(description, amount)
    duplicate_score = _duplicate_signal(description, peers)

    if duplicate_score >= 0.92:
        category = "duplicate_possible"
        confidence = max(confidence, 0.72)
    elif side == "ledger_only" and category == "needs_review":
        category = "missing_bank_line"
        confidence = 0.55
    elif side == "bank_only" and category == "needs_review":
        category = "missing_odoo_entry"
        confidence = 0.52

    if confidence < 0.55:
        category = "needs_review"

    label = ACTION_LABELS.get(category, ACTION_LABELS["needs_review"])
    suggested_action_label = label.get(language, label["en"])

    signal_parts = []
    if hits:
        signal_parts.append(f"keyword hits: {', '.join(hits[:4])}")
    if amount < 0:
        signal_parts.append("outflow amount")
    elif amount > 0:
        signal_parts.append("inflow amount")
    if entities["ibans"]:
        signal_parts.append("IBAN detected")
    if entities["references"]:
        signal_parts.append("reference detected")
    if duplicate_score >= 0.75:
        signal_parts.append(f"duplicate-like description score {duplicate_score:.2f}")

    if not signal_parts:
        signal_parts.append("no strong deterministic signal")

    explanation = f"Suggested from description, amount sign, and deterministic NLP signals ({'; '.join(signal_parts)}). No ERP posting was performed."

    return {
        "suggested_action": category,
        "suggested_action_label": suggested_action_label,
        "suggested_account_code": None,
        "suggested_account_name": None,
        "confidence": round(float(confidence), 2),
        "explanation": explanation,
        "detected_category": category,
        "detected_entities": entities,
        "nlp_signals": {
            "normalized_description": normalized[:500],
            "tokens": tokens[:30],
            "keyword_hits": hits,
            "amount_sign": "inflow" if amount > 0 else "outflow" if amount < 0 else "zero",
            "duplicate_similarity": round(duplicate_score, 3),
            "row_number": row_number,
            "vector_db_required": False,
        },
        "safe_to_post": False,
    }


def transaction_with_suggestion(transaction: Any, side: str, peers: list[dict[str, Any]] | None = None, language: str = "en") -> dict[str, Any]:
    payload = transaction.model_dump() if hasattr(transaction, "model_dump") else dict(transaction)
    payload.update(suggest_transaction_action(transaction, side=side, peers=peers, language=language))
    return payload
