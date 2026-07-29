"""Read-only local Odoo search across every account.

This route is intentionally separate from the account-code search. It handles
requests such as "search all accounts for the word Ghulam" without requiring an
external AI provider.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.deterministic_account_partner_search import (
    ARABIC_DIGITS,
    BASE_LINE_FIELDS,
    BASE_MOVE_FIELDS,
    FETCH_TERMS,
    MAX_ACCOUNT_LINES,
    SEARCH_TERM_PATTERN,
    STOP_WORDS,
    _many2one_id,
    _normalize,
    _read_account_lines,
    _read_connection,
    _read_fields,
    _read_moves,
    _select_fields,
    _value_text,
)
from app.api.v1.erp import ChatSpreadsheetRequest
from app.ml.name_matching.runtime import explain_similarity, get_local_name_matcher

logger = logging.getLogger(__name__)

GLOBAL_SCOPE_TERMS = (
    "جميع الحسابات",
    "كل الحسابات",
    "كافة الحسابات",
    "كامل الحسابات",
    "في الحسابات كلها",
    "كل القيود",
    "جميع القيود",
    "كافة القيود",
    "all accounts",
    "across all accounts",
    "every account",
    "all journal entries",
    "all entries",
)


def _extract_search_term(prompt: str) -> str | None:
    term_match = SEARCH_TERM_PATTERN.search(prompt)
    if not term_match:
        return None

    segment = term_match.group(1).strip().strip("\"'")
    tokens = re.findall(
        r"[A-Za-z\u0600-\u06FF][A-Za-z0-9_\-\u0600-\u06FF]*",
        segment,
    )
    selected_tokens: list[str] = []

    for token in tokens:
        normalized_token = _normalize(token)

        if normalized_token in STOP_WORDS:
            break
        if normalized_token in {"اسم", "name", "هو", "هي"}:
            continue

        selected_tokens.append(token)
        if len(selected_tokens) >= 4:
            break

    search_term = " ".join(selected_tokens).strip()
    if len(_normalize(search_term)) < 2:
        return None

    return search_term


def _extract_global_request(prompt: str) -> str | None:
    normalized_prompt = _normalize(prompt)

    if not any(_normalize(term) in normalized_prompt for term in FETCH_TERMS):
        return None

    if not any(_normalize(term) in normalized_prompt for term in GLOBAL_SCOPE_TERMS):
        return None

    # A prompt containing a specific account code belongs to the account-scoped
    # route, which runs before this route in the command router.
    translated_prompt = prompt.translate(ARABIC_DIGITS)
    if re.search(
        r"(?:الحساب|حساب|account)\s*[:#=\-–—]?\s*[0-9][0-9.\-]{3,20}",
        translated_prompt,
        re.IGNORECASE,
    ):
        return None

    return _extract_search_term(prompt)


def _read_accounts(
    erp: Any,
    account_ids: list[int],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}

    for start in range(0, len(account_ids), 200):
        chunk = account_ids[start : start + 200]
        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [[["id", "in", chunk]]],
            {
                "fields": ["id", "code", "name"],
                "limit": len(chunk),
            },
        )

        for account in accounts or []:
            account_id = account.get("id")
            if isinstance(account_id, int):
                result[account_id] = account

    return result


def try_hybrid_global_account_search(
    payload: ChatSpreadsheetRequest,
    db_session: Session,
) -> dict[str, Any] | None:
    search_term = _extract_global_request(payload.prompt or "")
    if not search_term:
        return None

    matcher = get_local_name_matcher()
    header = [
        "رقم القيد",
        "التاريخ",
        "الحالة",
        "الدفتر",
        "الشريك",
        "رمز الحساب",
        "اسم الحساب",
        "البيان",
        "مدين",
        "دائن",
        "المرجع",
        "حقل التطابق",
        "النص المطابق",
        "نسبة التطابق",
        "رابط Odoo",
    ]

    try:
        connection, erp = _read_connection(db_session)
        line_metadata = _read_fields(erp, "account.move.line")
        move_metadata = _read_fields(erp, "account.move")
        line_fields = _select_fields(line_metadata, BASE_LINE_FIELDS)
        move_fields = _select_fields(move_metadata, BASE_MOVE_FIELDS)

        domain: list[Any] = []
        if payload.company_id:
            domain.append(["company_id", "=", int(payload.company_id)])

        lines, total_lines, truncated = _read_account_lines(
            erp,
            domain,
            line_fields,
        )

        move_ids = sorted(
            {
                move_id
                for line in lines
                if (move_id := _many2one_id(line.get("move_id"))) is not None
            }
        )
        account_ids = sorted(
            {
                account_id
                for line in lines
                if (account_id := _many2one_id(line.get("account_id")))
                is not None
            }
        )
        moves = _read_moves(erp, move_ids, move_fields)
        accounts = _read_accounts(erp, account_ids)

        rows: list[list[str]] = [header]
        base_url = (connection.base_url or "").rstrip("/")

        for line in lines:
            move_id = _many2one_id(line.get("move_id"))
            move = moves.get(move_id or -1, {})
            best_result = None
            best_field = ""
            best_value = ""

            for field_name in line_fields:
                value = _value_text(line.get(field_name))
                if not value:
                    continue

                result = explain_similarity(search_term, value)
                if best_result is None or result.score > best_result.score:
                    best_result = result
                    best_field = f"account.move.line.{field_name}"
                    best_value = value

            for field_name in move_fields:
                value = _value_text(move.get(field_name))
                if not value:
                    continue

                result = explain_similarity(search_term, value)
                if best_result is None or result.score > best_result.score:
                    best_result = result
                    best_field = f"account.move.{field_name}"
                    best_value = value

            if best_result is None or best_result.decision != "match":
                continue

            account_id = _many2one_id(line.get("account_id"))
            account = accounts.get(account_id or -1, {})
            account_code = _value_text(account.get("code"))
            account_name = (
                _value_text(account.get("name"))
                or _value_text(line.get("account_id"))
            )
            partner_name = (
                _value_text(line.get("partner_id"))
                or _value_text(move.get("partner_id"))
            )
            entry_name = (
                _value_text(move.get("name"))
                or _value_text(line.get("move_id"))
            )
            reference = (
                _value_text(move.get("ref"))
                or _value_text(move.get("payment_reference"))
                or _value_text(line.get("ref"))
            )
            debit = float(line.get("debit") or 0.0)
            credit = float(line.get("credit") or 0.0)
            odoo_url = (
                f"{base_url}/web#id={move_id}&model=account.move&view_type=form"
                if base_url and move_id
                else ""
            )

            rows.append(
                [
                    entry_name,
                    _value_text(line.get("date"))
                    or _value_text(move.get("date")),
                    _value_text(move.get("state")),
                    _value_text(move.get("journal_id")),
                    partner_name,
                    account_code,
                    account_name,
                    _value_text(line.get("name")),
                    str(debit) if debit else "",
                    str(credit) if credit else "",
                    reference,
                    f"{best_field} [{best_result.reason}]",
                    best_value,
                    f"{best_result.score:.0%}",
                    odoo_url,
                ]
            )

        matched_count = len(rows) - 1
        if matched_count:
            message = (
                "✅ تم البحث محليًا في جميع حسابات Odoo دون Anthropic أو Ollama. "
                f"وجدت {matched_count} سطرًا مرتبطًا بالكلمة «{search_term}» "
                "أو كتابة قريبة موثوقة منها."
            )
        else:
            message = (
                "لم أجد نتائج مؤكدة في حسابات Odoo تطابق الكلمة "
                f"«{search_term}»."
            )

        message += f"\nتم فحص {len(lines)} من أصل {total_lines} سطر محاسبي."
        if truncated:
            message += (
                f"\n⚠️ تجاوزت البيانات حد الأمان {MAX_ACCOUNT_LINES} سطر؛ "
                "تم فحص أحدث السطور فقط."
            )

        return {
            "message": message,
            "grid_data": rows,
            "active_sheet_name": f"جميع الحسابات - {search_term}",
            "intent": "hybrid_global_account_search",
            "search_term": search_term,
            "matched_count": matched_count,
            "scanned_count": len(lines),
            "total_account_lines": total_lines,
            "truncated": truncated,
            "model_version": matcher.model_version,
            "match_threshold": matcher.accept_threshold,
        }

    except Exception:
        logger.exception("Hybrid global Odoo search failed.")
        return {
            "message": (
                "فهمت طلب البحث في جميع الحسابات، لكن تعذر إكمال القراءة من "
                "Odoo. تحقق من الاتصال وصلاحيات قراءة القيود المحاسبية."
            ),
            "grid_data": None,
            "intent": "hybrid_global_account_search",
            "search_term": search_term,
            "model_version": matcher.model_version,
        }
