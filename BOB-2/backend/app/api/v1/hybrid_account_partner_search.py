"""Bounded local Odoo search by exact account code and multilingual entity name."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.erp_spreadsheet import ChatSpreadsheetRequest
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
from app.api.v1.odoo_search_request import extract_account_search_request
from app.ml.name_matching.runtime import explain_similarity, get_local_name_matcher

logger = logging.getLogger(__name__)


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


def try_hybrid_account_partner_search(
    payload: ChatSpreadsheetRequest,
    db_session: Session,
) -> dict[str, Any] | None:
    extracted = extract_account_search_request(payload.prompt or "")
    if not extracted:
        return None

    account_code, search_term = extracted
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
        connection, erp = read_connection(db_session)

        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [[['code', '=', account_code]]],
            {"fields": ["id", "code", "name"], "limit": 50},
        )
        if not accounts:
            return {
                "message": f"لم أجد الحساب {account_code} داخل Odoo.",
                "grid_data": [header],
                "intent": "hybrid_account_partner_search",
                "account_code": account_code,
                "search_term": search_term,
                "model_version": matcher.model_version,
            }

        account_ids = [
            account["id"]
            for account in accounts
            if isinstance(account.get("id"), int)
        ]
        account_names = {
            account["id"]: value_text(account.get("name"))
            for account in accounts
            if isinstance(account.get("id"), int)
        }

        line_metadata = read_fields(erp, "account.move.line")
        move_metadata = read_fields(erp, "account.move")
        partner_metadata = read_fields(erp, "res.partner")
        line_fields = select_fields(line_metadata, BASE_LINE_FIELDS)
        move_fields = select_fields(move_metadata, BASE_MOVE_FIELDS)
        company_id = int(payload.company_id) if payload.company_id else None

        partner_candidates = discover_partner_candidates(
            erp,
            search_term=search_term,
            metadata=partner_metadata,
            company_id=company_id,
        )

        base_domain: list[Any] = [["account_id", "in", account_ids]]
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

        if candidate_result.successful_queries == 0:
            return {
                "message": (
                    "تم الاتصال بـ Odoo، لكن النظام رفض جميع استعلامات البحث "
                    "المفلترة للحساب. رمز التشخيص: ACCOUNT_QUERY_REJECTED."
                ),
                "grid_data": None,
                "intent": "hybrid_account_partner_search",
                "account_code": account_code,
                "search_term": search_term,
                "diagnostic_code": "ACCOUNT_QUERY_REJECTED",
            }

        lines = candidate_result.lines
        move_ids = sorted(
            {
                move_id
                for line in lines
                if (move_id := many2one_id(line.get("move_id"))) is not None
            }
        )
        moves = read_moves(erp, move_ids, move_fields)

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
                    account_code,
                    account_names.get(account_id or -1) or value_text(line.get("account_id")),
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
                "✅ تم البحث مباشرة في Odoo باستخدام النموذج المحلي الهجين. "
                f"وجدت {matched_count} حركة على الحساب {account_code} مرتبطة "
                f"بالكلمة «{search_term}»."
            )
        else:
            message = (
                f"لم أجد حركات مؤكدة على الحساب {account_code} تطابق الكلمة "
                f"«{search_term}»."
            )

        message += (
            f"\nتم فحص {partner_candidates.rows_scored} شريكًا و"
            f"{len(lines)} سطرًا مرشحًا فقط، دون تنزيل سجل الحساب كاملًا."
        )
        skipped_queries = (
            partner_candidates.skipped_queries + candidate_result.skipped_queries
        )
        if company_id:
            message += f"\nتم تقييد البحث بالشركة رقم {company_id}."
        if skipped_queries:
            message += (
                f"\nتم تجاوز {skipped_queries} استعلام اختياري رفضه Odoo "
                "دون إيقاف البحث."
            )

        return {
            "message": message,
            "grid_data": rows,
            "active_sheet_name": f"{account_code} - {search_term}",
            "intent": "hybrid_account_partner_search",
            "account_code": account_code,
            "search_term": search_term,
            "matched_count": matched_count,
            "candidate_count": len(lines),
            "partner_count": partner_candidates.rows_scored,
            "matched_partner_count": len(partner_candidates.partner_ids),
            "successful_queries": candidate_result.successful_queries,
            "skipped_queries": skipped_queries,
            "company_id": company_id,
            "model_version": matcher.model_version,
            "match_threshold": matcher.accept_threshold,
        }

    except Exception:
        logger.exception("Hybrid Odoo account/partner search failed.")
        return {
            "message": (
                "فهمت طلب البحث بالحساب والشريك، لكن تعذر تنفيذ البحث المباشر "
                "في Odoo. رمز التشخيص: ACCOUNT_SEARCH_STAGE_ERROR."
            ),
            "grid_data": None,
            "intent": "hybrid_account_partner_search",
            "account_code": account_code,
            "search_term": search_term,
            "diagnostic_code": "ACCOUNT_SEARCH_STAGE_ERROR",
        }
