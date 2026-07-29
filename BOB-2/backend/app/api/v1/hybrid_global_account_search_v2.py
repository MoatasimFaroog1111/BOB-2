"""Resilient read-only Odoo search across all accounts.

The route scores a bounded partner directory, then runs independent searches
on stable Odoo fields. One rejected optional query cannot abort the full request.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.deterministic_account_partner_search import (
    BASE_LINE_FIELDS,
    BASE_MOVE_FIELDS,
    _many2one_id,
    _read_connection,
    _read_fields,
    _read_moves,
    _value_text,
)
from app.api.v1.erp import ChatSpreadsheetRequest
from app.api.v1.hybrid_global_account_search import (
    _extract_global_request,
    _read_accounts,
)
from app.ml.name_matching.normalization import transliterate_arabic
from app.ml.name_matching.runtime import explain_similarity, get_local_name_matcher

logger = logging.getLogger(__name__)

MAX_PARTNERS_TO_SCORE = 5_000
MAX_CANDIDATE_LINES = 5_000
MAX_RESULTS_PER_QUERY = 1_200
MAX_SEARCH_TERMS = 8
STABLE_LINE_SEARCH_FIELDS = ("name", "ref")
STABLE_MOVE_SEARCH_FIELDS = ("ref", "payment_reference", "narration")


@dataclass
class SearchDiagnostics:
    stage: str = "initializing"
    partner_rows: int = 0
    matched_partners: int = 0
    candidate_rows: int = 0
    successful_queries: int = 0
    skipped_queries: int = 0


def _existing_fields(
    metadata: dict[str, dict[str, Any]],
    preferred: list[str],
) -> list[str]:
    if not metadata:
        return list(preferred)
    return [field for field in preferred if field in metadata]


def _company_prefix(company_id: int | None) -> list[Any]:
    return [["company_id", "=", int(company_id)]] if company_id else []


def _or_terms(field_name: str, terms: list[str]) -> list[Any]:
    leaves = [[field_name, "ilike", term] for term in terms if term]
    if not leaves:
        return []
    if len(leaves) == 1:
        return leaves
    return ["|"] * (len(leaves) - 1) + leaves


def _read_partner_directory(
    erp: Any,
    diagnostics: SearchDiagnostics,
) -> list[dict[str, Any]]:
    for fields in (["id", "name", "display_name", "ref"], ["id", "name"]):
        try:
            partners: list[dict[str, Any]] = []
            offset = 0
            while offset < MAX_PARTNERS_TO_SCORE:
                limit = min(500, MAX_PARTNERS_TO_SCORE - offset)
                batch = erp.execute_kw(
                    "res.partner",
                    "search_read",
                    [[]],
                    {
                        "fields": fields,
                        "order": "id asc",
                        "limit": limit,
                        "offset": offset,
                    },
                )
                if not batch:
                    break
                partners.extend(batch)
                offset += len(batch)
                if len(batch) < limit:
                    break
            diagnostics.partner_rows = len(partners)
            return partners
        except Exception:
            diagnostics.skipped_queries += 1
            logger.warning(
                "Partner directory read failed for fields=%s",
                fields,
                exc_info=True,
            )
    return []


def _matching_partners(
    search_term: str,
    partners: list[dict[str, Any]],
) -> tuple[list[int], list[str]]:
    threshold = get_local_name_matcher().accept_threshold
    matched_ids: list[int] = []
    matched_texts: list[str] = []

    for partner in partners:
        partner_id = partner.get("id")
        if not isinstance(partner_id, int):
            continue
        best_score = 0.0
        best_text = ""
        for field_name in ("name", "display_name", "ref"):
            text = _value_text(partner.get(field_name))
            if not text:
                continue
            score = explain_similarity(search_term, text).score
            if score > best_score:
                best_score = score
                best_text = text
        if best_score >= threshold:
            matched_ids.append(partner_id)
            if best_text:
                matched_texts.append(best_text)

    return matched_ids, matched_texts


def _search_terms(search_term: str, matched_texts: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = re.sub(r"\s+", " ", value or "").strip()
        key = cleaned.casefold()
        if len(cleaned) >= 2 and key not in seen:
            seen.add(key)
            ordered.append(cleaned)

    add(search_term)
    add(transliterate_arabic(search_term))
    for text in matched_texts:
        for token in re.findall(
            r"[A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF\-]*",
            text,
        ):
            if len(token) >= 3 and explain_similarity(search_term, token).decision == "match":
                add(token)
        if explain_similarity(search_term, text).decision == "match":
            add(text)
        if len(ordered) >= MAX_SEARCH_TERMS:
            break
    return ordered[:MAX_SEARCH_TERMS]


def _merge_lines(
    destination: dict[int, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    for row in rows or []:
        row_id = row.get("id")
        if isinstance(row_id, int):
            destination[row_id] = row


def _run_line_query(
    erp: Any,
    domain: list[Any],
    fields: list[str],
    destination: dict[int, dict[str, Any]],
    diagnostics: SearchDiagnostics,
) -> None:
    if not domain or len(destination) >= MAX_CANDIDATE_LINES:
        return
    limit = min(MAX_RESULTS_PER_QUERY, MAX_CANDIDATE_LINES - len(destination))
    try:
        rows = erp.execute_kw(
            "account.move.line",
            "search_read",
            [domain],
            {
                "fields": fields,
                "order": "date desc, id desc",
                "limit": limit,
            },
        )
        _merge_lines(destination, rows)
        diagnostics.successful_queries += 1
    except Exception:
        diagnostics.skipped_queries += 1
        logger.warning("Candidate query rejected: %s", domain, exc_info=True)


def _read_candidate_lines(
    erp: Any,
    *,
    company_id: int | None,
    matched_partner_ids: list[int],
    terms: list[str],
    line_fields: list[str],
    line_metadata: dict[str, dict[str, Any]],
    move_metadata: dict[str, dict[str, Any]],
    diagnostics: SearchDiagnostics,
) -> list[dict[str, Any]]:
    candidates: dict[int, dict[str, Any]] = {}
    company_domain = _company_prefix(company_id)

    if matched_partner_ids:
        _run_line_query(
            erp,
            company_domain + [["partner_id", "in", matched_partner_ids]],
            line_fields,
            candidates,
            diagnostics,
        )

    for field_name in STABLE_LINE_SEARCH_FIELDS:
        if line_metadata and field_name not in line_metadata:
            continue
        domain = _or_terms(field_name, terms)
        if domain:
            _run_line_query(
                erp,
                company_domain + domain,
                line_fields,
                candidates,
                diagnostics,
            )

    for field_name in STABLE_MOVE_SEARCH_FIELDS:
        if move_metadata and field_name not in move_metadata:
            continue
        domain = _or_terms(f"move_id.{field_name}", terms)
        if domain:
            _run_line_query(
                erp,
                company_domain + domain,
                line_fields,
                candidates,
                diagnostics,
            )

    diagnostics.candidate_rows = len(candidates)
    return sorted(
        candidates.values(),
        key=lambda row: (str(row.get("date") or ""), int(row.get("id") or 0)),
        reverse=True,
    )


def _best_match(
    search_term: str,
    line: dict[str, Any],
    move: dict[str, Any],
    line_fields: list[str],
    move_fields: list[str],
):
    best_result = None
    best_field = ""
    best_value = ""
    for model_name, record, fields in (
        ("account.move.line", line, line_fields),
        ("account.move", move, move_fields),
    ):
        for field_name in fields:
            value = _value_text(record.get(field_name))
            if not value:
                continue
            result = explain_similarity(search_term, value)
            if best_result is None or result.score > best_result.score:
                best_result = result
                best_field = f"{model_name}.{field_name}"
                best_value = value
    return best_result, best_field, best_value


def try_hybrid_global_account_search_v2(
    payload: ChatSpreadsheetRequest,
    db_session: Session,
) -> dict[str, Any] | None:
    search_term = _extract_global_request(payload.prompt or "")
    if not search_term:
        return None

    diagnostics = SearchDiagnostics()
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
        diagnostics.stage = "loading_model"
        matcher = get_local_name_matcher()
        diagnostics.stage = "connecting_to_odoo"
        connection, erp = _read_connection(db_session)
        diagnostics.stage = "reading_metadata"
        line_metadata = _read_fields(erp, "account.move.line")
        move_metadata = _read_fields(erp, "account.move")
        line_fields = _existing_fields(line_metadata, BASE_LINE_FIELDS)
        move_fields = _existing_fields(move_metadata, BASE_MOVE_FIELDS)

        diagnostics.stage = "reading_partner_directory"
        partners = _read_partner_directory(erp, diagnostics)
        diagnostics.stage = "matching_partners"
        matched_partner_ids, matched_partner_texts = _matching_partners(
            search_term,
            partners,
        )
        diagnostics.matched_partners = len(matched_partner_ids)
        terms = _search_terms(search_term, matched_partner_texts)

        diagnostics.stage = "reading_candidate_lines"
        company_id = int(payload.company_id) if payload.company_id else None
        lines = _read_candidate_lines(
            erp,
            company_id=company_id,
            matched_partner_ids=matched_partner_ids,
            terms=terms,
            line_fields=line_fields,
            line_metadata=line_metadata,
            move_metadata=move_metadata,
            diagnostics=diagnostics,
        )

        if diagnostics.successful_queries == 0:
            return {
                "message": (
                    "تم الاتصال بـ Odoo، لكن النظام رفض جميع استعلامات البحث "
                    "المرشحة. رمز التشخيص: GLOBAL_QUERY_REJECTED."
                ),
                "grid_data": None,
                "intent": "hybrid_global_account_search_v2",
                "search_term": search_term,
                "diagnostic_code": "GLOBAL_QUERY_REJECTED",
                "diagnostic_stage": diagnostics.stage,
            }

        diagnostics.stage = "reading_related_records"
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

        diagnostics.stage = "scoring_candidates"
        rows: list[list[str]] = [header]
        base_url = (connection.base_url or "").rstrip("/")

        for line in lines:
            move_id = _many2one_id(line.get("move_id"))
            move = moves.get(move_id or -1, {})
            best_result, best_field, best_value = _best_match(
                search_term,
                line,
                move,
                line_fields,
                move_fields,
            )
            if best_result is None or best_result.decision != "match":
                continue

            account_id = _many2one_id(line.get("account_id"))
            account = accounts.get(account_id or -1, {})
            account_code = _value_text(account.get("code"))
            account_name = _value_text(account.get("name")) or _value_text(
                line.get("account_id")
            )
            partner_name = _value_text(line.get("partner_id")) or _value_text(
                move.get("partner_id")
            )
            entry_name = _value_text(move.get("name")) or _value_text(
                line.get("move_id")
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
        message = (
            "✅ تم البحث محليًا في جميع حسابات Odoo دون مزود ذكاء خارجي. "
            f"وجدت {matched_count} سطرًا مرتبطًا بالكلمة «{search_term}»."
            if matched_count
            else (
                "لم أجد نتائج مؤكدة في حسابات Odoo تطابق الكلمة "
                f"«{search_term}»."
            )
        )
        message += (
            f"\nتم فحص {diagnostics.partner_rows} شريكًا و"
            f"{diagnostics.candidate_rows} سطرًا مرشحًا."
        )
        if diagnostics.skipped_queries:
            message += (
                f"\nتم تجاوز {diagnostics.skipped_queries} استعلام اختياري "
                "رفضه Odoo دون إيقاف البحث كله."
            )

        return {
            "message": message,
            "grid_data": rows,
            "active_sheet_name": f"جميع الحسابات - {search_term}",
            "intent": "hybrid_global_account_search_v2",
            "search_term": search_term,
            "matched_count": matched_count,
            "partner_count": diagnostics.partner_rows,
            "matched_partner_count": diagnostics.matched_partners,
            "candidate_count": diagnostics.candidate_rows,
            "successful_queries": diagnostics.successful_queries,
            "skipped_queries": diagnostics.skipped_queries,
            "model_version": matcher.model_version,
            "match_threshold": matcher.accept_threshold,
        }

    except Exception:
        logger.exception(
            "Resilient global Odoo search failed at stage=%s",
            diagnostics.stage,
        )
        return {
            "message": (
                "تعذر إكمال البحث المحلي في Odoo عند المرحلة «"
                f"{diagnostics.stage}». رمز التشخيص: GLOBAL_SEARCH_STAGE_ERROR."
            ),
            "grid_data": None,
            "intent": "hybrid_global_account_search_v2",
            "search_term": search_term,
            "diagnostic_code": "GLOBAL_SEARCH_STAGE_ERROR",
            "diagnostic_stage": diagnostics.stage,
        }
