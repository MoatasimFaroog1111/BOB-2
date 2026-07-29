"""Resilient read-only Odoo search across all accounts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.erp import ChatSpreadsheetRequest
from app.api.v1.global_account_search_common import (
    extract_global_request,
    read_account_map,
)
from app.api.v1.odoo_candidate_line_search import read_candidate_lines
from app.api.v1.odoo_partner_candidates import discover_partner_candidates
from app.api.v1.odoo_search_helpers import (
    BASE_LINE_FIELDS,
    BASE_MOVE_FIELDS,
    many2one_id,
    read_connection,
    read_fields,
    read_moves,
    select_fields,
    value_text,
)
from app.ml.name_matching.runtime import explain_similarity, get_local_name_matcher

logger = logging.getLogger(__name__)


@dataclass
class SearchDiagnostics:
    stage: str = "initializing"
    partner_rows: int = 0
    matched_partners: int = 0
    candidate_rows: int = 0
    successful_queries: int = 0
    skipped_queries: int = 0


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
            value = value_text(record.get(field_name))
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
    search_term = extract_global_request(payload.prompt or "")
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
        connection, erp = read_connection(db_session)

        diagnostics.stage = "reading_metadata"
        line_metadata = read_fields(erp, "account.move.line")
        move_metadata = read_fields(erp, "account.move")
        partner_metadata = read_fields(erp, "res.partner")
        line_fields = select_fields(line_metadata, BASE_LINE_FIELDS)
        move_fields = select_fields(move_metadata, BASE_MOVE_FIELDS)
        company_id = int(payload.company_id) if payload.company_id else None

        diagnostics.stage = "matching_partners"
        partner_candidates = discover_partner_candidates(
            erp,
            search_term=search_term,
            metadata=partner_metadata,
            company_id=company_id,
        )
        diagnostics.partner_rows = partner_candidates.rows_scored
        diagnostics.matched_partners = len(partner_candidates.partner_ids)
        diagnostics.skipped_queries += partner_candidates.skipped_queries

        diagnostics.stage = "reading_candidate_lines"
        base_domain: list[Any] = []
        if company_id:
            base_domain.append(["company_id", "=", company_id])

        candidate_result = read_candidate_lines(
            erp,
            base_domain=base_domain,
            matched_partner_ids=partner_candidates.partner_ids,
            terms=partner_candidates.search_terms,
            line_fields=line_fields,
            line_metadata=line_metadata,
            move_metadata=move_metadata,
        )
        lines = candidate_result.lines
        diagnostics.candidate_rows = len(lines)
        diagnostics.successful_queries = candidate_result.successful_queries
        diagnostics.skipped_queries += candidate_result.skipped_queries

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
                if (move_id := many2one_id(line.get("move_id"))) is not None
            }
        )
        account_ids = sorted(
            {
                account_id
                for line in lines
                if (account_id := many2one_id(line.get("account_id"))) is not None
            }
        )
        moves = read_moves(erp, move_ids, move_fields)
        accounts = read_account_map(erp, account_ids)

        diagnostics.stage = "scoring_candidates"
        rows: list[list[str]] = [header]
        base_url = (connection.base_url or "").rstrip("/")

        for line in lines:
            move_id = many2one_id(line.get("move_id"))
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

            account_id = many2one_id(line.get("account_id"))
            account = accounts.get(account_id or -1, {})
            partner_name = value_text(line.get("partner_id")) or value_text(
                move.get("partner_id")
            )
            entry_name = value_text(move.get("name")) or value_text(
                line.get("move_id")
            )
            reference = (
                value_text(move.get("ref"))
                or value_text(move.get("payment_reference"))
                or value_text(line.get("ref"))
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
                    value_text(line.get("date")) or value_text(move.get("date")),
                    value_text(move.get("state")),
                    value_text(move.get("journal_id")),
                    partner_name,
                    value_text(account.get("code")),
                    value_text(account.get("name")) or value_text(line.get("account_id")),
                    value_text(line.get("name")),
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
                "✅ تم البحث محليًا في جميع حسابات Odoo دون مزود ذكاء خارجي. "
                f"وجدت {matched_count} سطرًا مرتبطًا بالكلمة «{search_term}»."
            )
        else:
            message = (
                "لم أجد نتائج مؤكدة في حسابات Odoo تطابق الكلمة "
                f"«{search_term}»."
            )

        message += (
            f"\nتم فحص {diagnostics.partner_rows} شريكًا و"
            f"{diagnostics.candidate_rows} سطرًا مرشحًا."
        )
        if payload.company_id:
            message += f"\nتم تقييد البحث بالشركة رقم {int(payload.company_id)}."
        if partner_candidates.truncated:
            message += "\n⚠️ تم بلوغ حد فحص دليل الشركاء."
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
            "company_id": company_id,
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
