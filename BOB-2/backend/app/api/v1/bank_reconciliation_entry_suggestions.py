from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value

router = APIRouter()


class BankTxnForSuggestion(BaseModel):
    date: str = ""
    description: str = ""
    amount: float = 0.0
    row_number: Optional[int] = None
    suggested_action: Optional[str] = None
    suggested_action_label: Optional[str] = None
    explanation: Optional[str] = None
    detected_category: Optional[str] = None


class HistoricalEntrySuggestionRequest(BaseModel):
    transactions: list[BankTxnForSuggestion] = Field(default_factory=list)
    company_id: Optional[int] = None
    bank_journal_id: Optional[int] = None
    bank_account_id: Optional[int] = None
    history_limit: int = 500


def _get_active_erp_provider(db: Session):
    conn = db.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True,  # noqa: E712
    ).first()
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active ERP connection found. Please connect Odoo first.")

    try:
        secret = json.loads(decrypt_value(conn.encrypted_secret_ref or "{}"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to decrypt ERP connection credentials.") from exc

    return get_erp_provider(
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=secret.get("username", ""),
        password=secret.get("password", ""),
    )


def _m2o(value: Any) -> tuple[Optional[int], str]:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0]) if value[0] else None, str(value[1] if len(value) > 1 else "")
    if isinstance(value, int):
        return value, ""
    return None, ""


def _norm(text: Any) -> str:
    value = str(text or "").lower()
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    value = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", " ", value)
    value = re.sub(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", " ", value)
    value = re.sub(r"\b(ref|reference|txn|transaction|date|time|sar|vat|iban|swift|mada|visa|card|bank)\b", " ", value)
    value = re.sub(r"[^\w\u0600-\u06FF]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _tokens(text: Any) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 2 and not t.isdigit()}


def _category(text: str) -> str:
    t = _norm(text)
    if re.search(r"رسوم|عموله|fee|charge|commission", t):
        return "bank_fees"
    if re.search(r"راتب|رواتب|salary|payroll|wps", t):
        return "payroll"
    if re.search(r"ضريبه|زكاه|زكاة|vat|tax", t):
        return "tax"
    if re.search(r"سداد|sadad|bill|فاتوره|فاتورة|mol|government", t):
        return "bill_payment"
    if re.search(r"تحويل|transfer|local transfer|instant payment", t):
        return "transfer"
    if re.search(r"pos|شبكه|مدي|مدى|card settlement|settlement", t):
        return "pos_settlement"
    return "general"


def _amount_similarity(a: float, b: float) -> float:
    a = abs(float(a or 0.0))
    b = abs(float(b or 0.0))
    if a == 0 or b == 0:
        return 0.0
    ratio = min(a, b) / max(a, b)
    if ratio >= 0.995:
        return 1.0
    if ratio >= 0.98:
        return 0.82
    if ratio >= 0.95:
        return 0.65
    if ratio >= 0.90:
        return 0.45
    return 0.0


def _text_similarity(a: str, b: str) -> float:
    na = _norm(a)
    nb = _norm(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta = _tokens(na)
    tb = _tokens(nb)
    overlap = len(ta & tb) / max(len(ta | tb), 1)
    return max(seq, overlap)


def _line_text(line: dict[str, Any]) -> str:
    move_id, move_name = _m2o(line.get("move_id"))
    partner_id, partner_name = _m2o(line.get("partner_id"))
    account_id, account_name = _m2o(line.get("account_id"))
    return " ".join(filter(None, [
        str(line.get("name") or ""),
        str(line.get("ref") or ""),
        move_name,
        partner_name,
        account_name,
    ]))


def _entry_amount(line: dict[str, Any]) -> float:
    debit = float(line.get("debit") or 0.0)
    credit = float(line.get("credit") or 0.0)
    balance = line.get("balance")
    if balance is not None:
        return float(balance or 0.0)
    return debit - credit


def _fetch_historical_bank_entries(erp: Any, payload: HistoricalEntrySuggestionRequest) -> list[dict[str, Any]]:
    domain: list[Any] = [["parent_state", "=", "posted"]]
    if payload.company_id:
        domain.append(["company_id", "=", int(payload.company_id)])
    if payload.bank_journal_id:
        domain.append(["journal_id", "=", int(payload.bank_journal_id)])
    if payload.bank_account_id:
        domain.append(["account_id", "=", int(payload.bank_account_id)])

    fields = ["id", "date", "name", "ref", "move_id", "account_id", "partner_id", "debit", "credit", "balance", "journal_id"]
    bank_lines = erp.execute_kw(
        "account.move.line",
        "search_read",
        [domain],
        {"fields": fields, "order": "date desc, id desc", "limit": max(50, min(int(payload.history_limit or 500), 1000))},
    )
    if not bank_lines and payload.bank_journal_id:
        fallback_domain = [["parent_state", "=", "posted"], ["journal_id", "=", int(payload.bank_journal_id)]]
        if payload.company_id:
            fallback_domain.append(["company_id", "=", int(payload.company_id)])
        bank_lines = erp.execute_kw(
            "account.move.line",
            "search_read",
            [fallback_domain],
            {"fields": fields, "order": "date desc, id desc", "limit": max(50, min(int(payload.history_limit or 500), 1000))},
        )

    move_ids = sorted({mid for mid, _name in (_m2o(line.get("move_id")) for line in bank_lines) if mid})
    if not move_ids:
        return []

    all_lines = erp.execute_kw(
        "account.move.line",
        "search_read",
        [[["move_id", "in", move_ids], ["parent_state", "=", "posted"]]],
        {"fields": fields + ["analytic_account_id"], "order": "date desc, id asc", "limit": min(len(move_ids) * 8, 4000)},
    )

    by_move: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line in all_lines:
        move_id, _ = _m2o(line.get("move_id"))
        if move_id:
            by_move[move_id].append(line)

    historical: list[dict[str, Any]] = []
    for bank_line in bank_lines:
        move_id, move_name = _m2o(bank_line.get("move_id"))
        if not move_id:
            continue
        bank_account_id, _bank_account_name = _m2o(bank_line.get("account_id"))
        related_lines = by_move.get(move_id, [])
        counterpart_lines = []
        for line in related_lines:
            account_id, account_name = _m2o(line.get("account_id"))
            if payload.bank_account_id and account_id == int(payload.bank_account_id):
                continue
            if not payload.bank_account_id and account_id == bank_account_id:
                continue
            debit = abs(float(line.get("debit") or 0.0))
            credit = abs(float(line.get("credit") or 0.0))
            if debit == 0 and credit == 0:
                continue
            counterpart_lines.append(line)
        if not counterpart_lines:
            continue
        historical.append({
            "move_id": move_id,
            "move_name": move_name,
            "date": bank_line.get("date") or "",
            "bank_text": _line_text(bank_line),
            "bank_amount": _entry_amount(bank_line),
            "counterparts": counterpart_lines,
        })
    return historical


def _suggest_for_txn(txn: BankTxnForSuggestion, historical: list[dict[str, Any]]) -> dict[str, Any]:
    # Historical matching intentionally ignores dates. Dates are kept only for display/evidence.
    # Ranking is driven mainly by description/statement text, with amount as a light supporting signal.
    txn_text = " ".join(filter(None, [txn.description, txn.suggested_action_label, txn.explanation, txn.detected_category]))
    txn_cat = _category(txn_text)
    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None

    for entry in historical:
        bank_text_score = _text_similarity(txn_text, entry.get("bank_text") or "")
        amount_score = _amount_similarity(txn.amount, entry.get("bank_amount") or 0.0)
        cat_score = 1.0 if txn_cat != "general" and txn_cat == _category(entry.get("bank_text") or "") else 0.0

        for counter in entry["counterparts"]:
            account_id, account_label = _m2o(counter.get("account_id"))
            if not account_id:
                continue
            partner_id, partner_label = _m2o(counter.get("partner_id"))
            analytic_id, analytic_label = _m2o(counter.get("analytic_account_id"))
            counter_text_score = _text_similarity(txn_text, _line_text(counter))
            text_score = max(bank_text_score, counter_text_score)
            score = min(text_score * 0.82 + amount_score * 0.12 + cat_score * 0.06, 1.0)
            if best is None or score > best[0]:
                best = (score, entry, counter)

    if not best:
        return {
            "row_number": txn.row_number,
            "date": txn.date,
            "description": txn.description,
            "amount": txn.amount,
            "confidence": 0.0,
            "source": "odoo_historical_move_lines",
            "reason": "No sufficiently similar posted historical bank entry was found in Odoo.",
            "needs_review": True,
        }

    score, entry, counter = best
    account_id, account_label = _m2o(counter.get("account_id"))
    partner_id, partner_label = _m2o(counter.get("partner_id"))
    analytic_id, analytic_label = _m2o(counter.get("analytic_account_id"))
    reason = (
        f"Matched against historical posted Odoo move {entry.get('move_name') or entry.get('move_id')} "
        f"using description/statement similarity as the main factor and amount as a light supporting factor. Date was not used for scoring."
    )
    return {
        "row_number": txn.row_number,
        "date": txn.date,
        "description": txn.description,
        "amount": txn.amount,
        "suggested_account_id": account_id,
        "suggested_account_label": account_label,
        "suggested_partner_id": partner_id,
        "suggested_partner_label": partner_label,
        "suggested_analytic_account_id": analytic_id,
        "suggested_analytic_account_label": analytic_label,
        "confidence": round(score, 4),
        "source": "odoo_historical_move_lines",
        "reason": reason,
        "historical_move_id": entry.get("move_id"),
        "historical_move_name": entry.get("move_name"),
        "historical_date": entry.get("date"),
        "needs_review": score < 0.60,
    }


@router.post("/bank-reconciliation/entry-suggestions")
def suggest_bank_reconciliation_entries(payload: HistoricalEntrySuggestionRequest, db: Session = Depends(get_db)):
    if not payload.transactions:
        return {"status": "success", "items": [], "history_count": 0, "method": "odoo_historical_description_amount_similarity"}

    erp = _get_active_erp_provider(db)
    try:
        historical = _fetch_historical_bank_entries(erp, payload)
        items = [_suggest_for_txn(txn, historical) for txn in payload.transactions]
        confident = len([item for item in items if not item.get("needs_review")])
        return {
            "status": "success",
            "items": items,
            "history_count": len(historical),
            "confident_count": confident,
            "method": "odoo_historical_description_amount_similarity",
            "safe_to_post": False,
            "note": "Historical suggestions are matched mainly by description/statement text. Amount is only a supporting signal, and transaction dates are not used for scoring.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to build historical journal entry suggestions: {exc}") from exc
