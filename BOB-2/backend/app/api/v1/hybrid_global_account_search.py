"""Read-only local Odoo search across every account.

The global route first identifies matching partners, then asks Odoo only for
candidate journal lines. It deliberately avoids downloading and scoring every
accounting line in one browser request.
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
    SEARCH_BATCH_SIZE,
    SEARCH_TERM_PATTERN,
    STOP_WORDS,
    TEXT_FIELD_HINTS,
    _many2one_id,
    _normalize,
    _read_connection,
    _read_fields,
    _read_moves,
    _select_fields,
    _value_text,
)
from app.api.v1.erp import ChatSpreadsheetRequest
from app.ml.name_matching.normalization import transliterate_arabic
from app.ml.name_matching.runtime import explain_similarity, get_local_name_matcher

logger = logging.getLogger(__name__)

MAX_PARTNERS_TO_SCORE = 10_000
MAX_CANDIDATE_LINES = 5_000
MAX_DIRECT_SEARCH_FIELDS = 12
MAX_DIRECT_SEARCH_TERMS = 20

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

    translated_prompt = prompt.translate(ARABIC_DIGITS)
    if re.search(
        r"(?:الحساب|حساب|account)\s*[:#=\-–—]?\s*[0-9][0-9.\-]{3,20}",
        translated_prompt,
        re.IGNORECASE,
    ):
        return None

    return _extract_search_term(prompt)


def _or_domain(conditions: list[list[Any]]) -> list[Any]:
    if not conditions:
        return []
    if len(conditions) == 1:
        return conditions
    return ["|"] * (len(conditions) - 1) + conditions


def _partner_fields(metadata: dict[str, dict[str, Any]]) -> list[str]:
    preferred = [
        "id",
        "name",
        "display_name",
        "commercial_company_name",
        "ref",
    ]
    if not metadata:
        return ["id", "name"]
    return [field for field in preferred if field in metadata]


def _read_partners(
    erp: Any,
    metadata: dict[str, dict[str, Any]],
    company_id: int | None,
) -> tuple[list[dict[str, Any]], bool]:
    fields = _partner_fields(metadata)
    domain: list[Any] = []

    if company_id and "company_id" in metadata:
        domain = [
            "|",
            ["company_id", "=", False],
            ["company_id", "=", int(company_id)],
        ]

    partners: list[dict[str, Any]] = []
    offset = 0

    while offset < MAX_PARTNERS_TO_SCORE:
        batch_limit = min(500, MAX_PARTNERS_TO_SCORE - offset)
        batch = erp.execute_kw(
            "res.partner",
            "search_read",
            [domain],
            {
                "fields": fields,
                "order": "id asc",
                "limit": batch_limit,
                "offset": offset,
            },
        )
        if not batch:
            break

        partners.extend(batch)
        offset += len(batch)
        if len(batch) < batch_limit:
            break

    return partners, len(partners) >= MAX_PARTNERS_TO_SCORE


def _matching_partner_ids(
    search_term: str,
    partners: list[dict[str, Any]],
) -> tuple[list[int], list[str]]:
    matched_ids: list[int] = []
    matched_texts: list[str] = []

    for partner in partners:
        partner_id = partner.get("id")
        if not isinstance(partner_id, int):
            continue

        best_score = 0.0
        best_text = ""

        for field_name, value in partner.items():
            if field_name == "id":
                continue
            text = _value_text(value)
            if not text:
                continue

            result = explain_similarity(search_term, text)
            if result.score > best_score:
                best_score = result.score
                best_text = text

        if best_score >= get_local_name_matcher().accept_threshold:
            matched_ids.append(partner_id)
            if best_text:
                matched_texts.append(best_text)

    return matched_ids, matched_texts


def _direct_search_terms(
    search_term: str,
    matched_partner_texts: list[str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = re.sub(r"\s+", " ", value or "").strip()
        key = cleaned.casefold()
        if len(cleaned) < 2 or key in seen:
            return
        seen.add(key)
        ordered.append(cleaned)

    add(search_term)
    add(transliterate_arabic(search_term))

    for text in matched_partner_texts:
        for token in re.findall(r"[A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF\-]*", text):
            if len(token) < 3:
                continue
            result = explain_similarity(search_term, token)
            if result.decision == "match":
                add(token)

        if explain_similarity(search_term, text).decision == "match":
            add(text)

        if len(ordered) >= MAX_DIRECT_SEARCH_TERMS:
            break

    return ordered[:MAX_DIRECT_SEARCH_TERMS]


def _direct_text_fields(
    metadata: dict[str, dict[str, Any]],
    preferred: tuple[str, ...],
) -> list[str]:
    fields: list[str] = []

    for field_name in preferred:
        definition = metadata.get(field_name)
        if definition and definition.get("type") in {"char", "text", "html", "reference"}:
            fields.append(field_name)

    for field_name, definition in metadata.items():
        if field_name in fields:
            continue
        if definition.get("type") not in {"char", "text", "html", "reference"}:
            continue

        searchable = f"{field_name} {definition.get('string') or ''}".lower()
        if not any(hint in searchable for hint in TEXT_FIELD_HINTS):
            continue

        fields.append(field_name)
        if len(fields) >= MAX_DIRECT_SEARCH_FIELDS:
            break

    return fields[:MAX_DIRECT_SEARCH_FIELDS]


def _candidate_domain(
    *,
    company_id: int | None,
    matched_partner_ids: list[int],
    search_terms: list[str],
    line_metadata: dict[str, dict[str, Any]],
    move_metadata: dict[str, dict[str, Any]],
) -> list[Any]:
    conditions: list[list[Any]] = []

    if matched_partner_ids:
        conditions.append(["partner_id", "in", matched_partner_ids])

    line_search_fields = _direct_text_fields(line_metadata, ("name", "ref"))
    move_search_fields = _direct_text_fields(
        move_metadata,
        ("ref", "payment_reference", "narration"),
    )

    for term in search_terms:
        for field_name in line_search_fields:
            conditions.append([field_name, "ilike", term])
        for field_name in move_search_fields:
            conditions.append([f"move_id.{field_name}", "ilike", term])

    if not conditions:
        return []

    domain: list[Any] = []
    if company_id:
        domain.append(["company_id", "=", int(company_id)])
    domain.extend(_or_domain(conditions))
    return domain


def _read_candidate_lines(
    erp: Any,
    domain: list[Any],
    fields: list[str],
) -> tuple[list[dict[str, Any]], int, bool]:
    if not domain:
        return [], 0, False

    total_count = int(
        erp.execute_kw(
            "account.move.line",
            "search_count",
            [domain],
        )
        or 0
    )
    target_count = min(total_count, MAX_CANDIDATE_LINES)
    lines: list[dict[str, Any]] = []
    offset = 0

    while offset < target_count:
        batch_limit = min(SEARCH_BATCH_SIZE, target_count - offset)
        batch = erp.execute_kw(
            "account.move.line",
            "search_read",
            [domain],
            {
                "fields": fields,
                "order": "date desc, id desc",
                "limit": batch_limit,
                "offset": offset,
            },
        )
        if not batch:
            break

        lines.extend(batch)
        offset += len(batch)
        if len(batch) < batch_limit:
            break

    return lines, total_count, total_count > len(lines)


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
        matcher = get_local_name_matcher()
        connection, erp = _read_connection(db_session)
        line_metadata = _read_fields(erp, "account.move.line")
        move_metadata = _read_fields(erp, "account.move")
        partner_metadata = _read_fields(erp, "res.partner")
        line_fields = _select_fields(line_metadata, BASE_LINE_FIELDS)
        move_fields = _select_fields(move_metadata, BASE_MOVE_FIELDS)

        company_id = int(payload.company_id) if payload.company_id else None
        partners, partners_truncated = _read_partners(
            erp,
            partner_metadata,
            company_id,
        )
        matched_partner_ids, matched_partner_texts = _matching_partner_ids(
            search_term,
            partners,
        )
        search_terms = _direct_search_terms(search_term, matched_partner_texts)
        domain = _candidate_domain(
            company_id=company_id,
            matched_partner_ids=matched_partner_ids,
            search_terms=search_terms,
            line_metadata=line_metadata,
            move_metadata=move_metadata,
        )
        lines, total_candidates, candidates_truncated = _read_candidate_lines(
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
                if (account_id := _many2one_id(line.get("account_id"))) is not None
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

        message += (
            f"\nتم فحص {len(partners)} شريكًا، ثم {len(lines)} سطرًا مرشحًا "
            f"من أصل {total_candidates} سطر مرشح في Odoo."
        )
        if partners_truncated:
            message += (
                f"\n⚠️ تجاوز عدد الشركاء حد الأمان {MAX_PARTNERS_TO_SCORE}."
            )
        if candidates_truncated:
            message += (
                f"\n⚠️ تجاوزت النتائج المرشحة حد الأمان {MAX_CANDIDATE_LINES}؛ "
                "تم فحص أحدث المرشحين فقط."
            )

        return {
            "message": message,
            "grid_data": rows,
            "active_sheet_name": f"جميع الحسابات - {search_term}",
            "intent": "hybrid_global_account_search",
            "search_term": search_term,
            "matched_count": matched_count,
            "partner_count": len(partners),
            "matched_partner_count": len(matched_partner_ids),
            "candidate_count": total_candidates,
            "scanned_count": len(lines),
            "truncated": partners_truncated or candidates_truncated,
            "model_version": matcher.model_version,
            "match_threshold": matcher.accept_threshold,
        }

    except Exception:
        logger.exception("Hybrid global Odoo search failed.")
        return {
            "message": (
                "فهمت طلب البحث في جميع الحسابات، لكن تعذر إكمال القراءة من "
                "Odoo. راجع سجل Backend لمعرفة سبب الاتصال أو مهلة التنفيذ."
            ),
            "grid_data": None,
            "intent": "hybrid_global_account_search",
            "search_term": search_term,
        }
