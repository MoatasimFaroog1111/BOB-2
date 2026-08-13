"""Feature engineering for accounting learning and inference.

Only information that can exist before posting is allowed into model input.
Target labels such as accounts, journal, taxes, analytics and post-generated move
identifiers are excluded to prevent target leakage and misleading offline accuracy.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ml.accounting_intelligence.contracts import HistoricalAccountingExample


def normalize_accounting_text(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"[^\w\u0600-\u06ff.%:/@+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def amount_bucket(value: float | int | str | Decimal | None) -> str:
    if value in (None, ""):
        return "unknown"
    try:
        amount = abs(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return "unknown"
    if amount == 0:
        return "zero"
    if amount < 100:
        return "lt_100"
    if amount < 1_000:
        return "100_999"
    if amount < 10_000:
        return "1k_9k"
    if amount < 100_000:
        return "10k_99k"
    if amount < 1_000_000:
        return "100k_999k"
    return "gte_1m"


def infer_document_signals(text: str) -> dict[str, Any]:
    n = normalize_accounting_text(text)
    signals: dict[str, Any] = {
        "vat_relevant": any(token in n for token in ("vat", "ضريبه", "ضريبي", "15%")),
        "bank_related": any(token in n for token in ("bank", "iban", "بنك", "تحويل", "swift")),
        "payroll_related": any(token in n for token in ("salary", "payroll", "راتب", "رواتب")),
        "asset_related": any(token in n for token in ("fixed asset", "asset", "اصل", "اصول")),
        "revenue_related": any(token in n for token in ("revenue", "sales", "مبيعات", "ايراد")),
        "expense_related": any(token in n for token in ("expense", "fee", "rent", "مصروف", "رسوم", "ايجار")),
    }
    return signals


def build_historical_feature_text(
    *,
    reference: str | None,
    narration: str | None,
    payment_reference: str | None,
    invoice_origin: str | None,
    partner_name: str | None,
    line_descriptions: list[str],
    product_names: list[str],
    attachment_features: list[str],
    amount: float | None,
    move_type: str | None,
    currency: str | None,
    move_name: str | None = None,
    journal_name: str | None = None,
) -> str:
    """Build pre-posting input without target leakage.

    ``move_name`` and ``journal_name`` are accepted only for backwards-compatible
    callers and are intentionally ignored because both are post/accounting-routing
    outcomes rather than evidence available on a new incoming document or command.
    """
    del move_name, journal_name
    parts = [
        reference,
        narration,
        payment_reference,
        invoice_origin,
        partner_name,
        " ".join(line_descriptions),
        " ".join(product_names),
        " ".join(attachment_features),
        f"amount_bucket:{amount_bucket(amount)}",
        f"move_type:{move_type or 'unknown'}",
        f"currency:{currency or 'unknown'}",
    ]
    return normalize_accounting_text(" | ".join(str(part) for part in parts if part))


def structured_features(example: HistoricalAccountingExample) -> dict[str, Any]:
    signals = infer_document_signals(example.text)
    return {
        "amount_bucket": amount_bucket(example.amount),
        "move_type": example.move_type,
        "currency": example.currency,
        "has_attachments": bool(example.attachment_features),
        **signals,
        **(example.feature_metadata or {}),
    }


def lexical_account_score(text: str, account: dict[str, Any]) -> float:
    """Small explainable score for chart-of-account candidate semantics."""
    query_tokens = set(normalize_accounting_text(text).split())
    if not query_tokens:
        return 0.0
    account_text = normalize_accounting_text(
        " ".join(
            str(account.get(key) or "")
            for key in ("code", "name", "account_type")
        )
    )
    account_tokens = set(account_text.split())
    if not account_tokens:
        return 0.0
    overlap = len(query_tokens & account_tokens) / max(len(query_tokens), 1)
    code = normalize_accounting_text(str(account.get("code") or ""))
    code_bonus = 0.08 if code and code in normalize_accounting_text(text) else 0.0
    return min(1.0, overlap + code_bonus)
