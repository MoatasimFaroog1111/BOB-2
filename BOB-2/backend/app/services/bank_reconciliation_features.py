"""Pure feature extraction for bank reconciliation suggestions."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.services.bank_rules_engine import transaction_statement_text

_MONEY = Decimal("0.01")


def decimal_amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def money_float(value: Decimal) -> float:
    return float(value.quantize(_MONEY, rounding=ROUND_HALF_UP))


def normalize_text(text: Any) -> str:
    value = str(text or "").lower()
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    value = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", " ", value)
    value = re.sub(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", " ", value)
    value = re.sub(
        r"\b(ref|reference|txn|transaction|date|time|sar|iban|swift|mada|visa|card|bank)\b",
        " ",
        value,
    )
    value = re.sub(r"[^\w\u0600-\u06FF]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def text_tokens(text: Any) -> set[str]:
    return {token for token in normalize_text(text).split() if len(token) > 2 and not token.isdigit()}


def transaction_category(text: str) -> str:
    normalized = normalize_text(text)
    if re.search(r"رسوم|عموله|fee|charge|commission", normalized):
        return "bank_fees"
    if re.search(r"راتب|رواتب|salary|payroll|wps", normalized):
        return "payroll"
    if re.search(r"ضريبه|زكاه|زكاة|vat|tax", normalized):
        return "tax"
    if re.search(r"سداد|sadad|bill|فاتوره|فاتورة|mol|government", normalized):
        return "bill_payment"
    if re.search(r"تحويل|transfer|local transfer|instant payment", normalized):
        return "transfer"
    if re.search(r"pos|شبكه|مدي|مدى|card settlement|settlement", normalized):
        return "pos_settlement"
    return "general"


def amount_similarity(left: Any, right: Any) -> float:
    a = abs(decimal_amount(left))
    b = abs(decimal_amount(right))
    if a == 0 or b == 0:
        return 0.0
    ratio = min(a, b) / max(a, b)
    if ratio >= Decimal("0.995"):
        return 1.0
    if ratio >= Decimal("0.98"):
        return 0.82
    if ratio >= Decimal("0.95"):
        return 0.65
    if ratio >= Decimal("0.90"):
        return 0.45
    return 0.0


def text_similarity(left: str, right: str) -> float:
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    left_tokens = text_tokens(a)
    right_tokens = text_tokens(b)
    union = left_tokens | right_tokens
    overlap = len(left_tokens & right_tokens) / max(len(union), 1)
    containment = 0.0
    if left_tokens and right_tokens:
        containment = len(left_tokens & right_tokens) / max(min(len(left_tokens), len(right_tokens)), 1)
    return min(1.0, max(sequence, overlap, containment * 0.96))


def direction_similarity(left: Any, right: Any) -> float:
    a = decimal_amount(left)
    b = decimal_amount(right)
    if a == 0 or b == 0:
        return 0.0
    return 1.0 if (a > 0) == (b > 0) else 0.0


def transaction_text(transaction: dict[str, Any]) -> str:
    values = [
        transaction_statement_text(transaction),
        str(transaction.get("suggested_action_label") or ""),
        str(transaction.get("explanation") or ""),
        str(transaction.get("detected_category") or ""),
    ]
    return " ".join(value for value in values if value).strip()


def is_tax_account_label(label: str) -> bool:
    normalized = normalize_text(label)
    return bool(re.search(r"\bvat\b|input vat|vat input|value added tax|ضريبه|ضريبة|104041", normalized))


def _first_money(patterns: Iterable[re.Pattern[str]], text: str) -> Decimal:
    normalized = str(text or "").replace(",", " ")
    for pattern in patterns:
        match = pattern.search(normalized)
        if not match or not match.group(1):
            continue
        raw = re.sub(r"[^0-9.]", "", match.group(1))
        try:
            value = Decimal(raw).quantize(_MONEY, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            continue
        if value > 0:
            return value
    return Decimal("0.00")


def detect_monetary_components(transaction: dict[str, Any]) -> dict[str, Any]:
    """Extract bank-fee/VAT components without inventing a tax amount."""
    total = abs(decimal_amount(transaction.get("amount")))
    text = transaction_text(transaction)
    if total <= 0:
        return {
            "gross_amount": 0.0,
            "fee_amount": 0.0,
            "vat_amount": 0.0,
            "vat_rate": None,
            "components_reconcile_to_total": False,
        }

    fee = _first_money(
        (
            re.compile(r"\bFEE\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
            re.compile(r"\b(?:BANK\s*)?CHARGE\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
            re.compile(r"(?:رسوم|عموله|عمولة)\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
        ),
        text,
    )
    vat = _first_money(
        (
            re.compile(r"VAT\s*AMOUNT\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
            re.compile(
                r"(?:ضريبه|ضريبة)\s*(?:القيمه|القيمة)?\s*(?:المضافه|المضافة)?\s*0*([0-9]+(?:\.[0-9]+)?)",
                re.IGNORECASE,
            ),
        ),
        text,
    )
    if vat >= total:
        vat = Decimal("0.00")

    vat_rate: Decimal | None = None
    has_15_percent_signal = bool(
        re.search(
            r"VAT\s*%?\s*15|VAT%\s*15|15\s*%|ضريبه\s*القيمه\s*المضافه|الضريبة\s*القيمة\s*المضافة",
            text,
            re.IGNORECASE,
        )
    )
    if has_15_percent_signal:
        vat_rate = Decimal("15.00")
        if vat <= 0:
            vat = (total * Decimal("15") / Decimal("115")).quantize(_MONEY, rounding=ROUND_HALF_UP)

    if fee > total:
        fee = Decimal("0.00")
    if fee <= 0 and vat > 0 and transaction_category(text) == "bank_fees":
        fee = max(Decimal("0.00"), total - vat)

    reconciles = fee > 0 and vat >= 0 and abs((fee + vat) - total) <= Decimal("0.02")
    return {
        "gross_amount": money_float(total),
        "fee_amount": money_float(fee),
        "vat_amount": money_float(vat),
        "vat_rate": money_float(vat_rate) if vat_rate is not None else None,
        "components_reconcile_to_total": bool(reconciles),
    }
