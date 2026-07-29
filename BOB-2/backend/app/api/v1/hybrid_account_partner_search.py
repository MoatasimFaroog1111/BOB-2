"""Hybrid local Odoo search by account code and multilingual entity name.

The Odoo retrieval helpers remain in the deterministic module. This module
replaces only the scoring stage, keeping the database/Odoo behavior isolated
and read-only.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.deterministic_account_partner_search import (
    BASE_LINE_FIELDS,
    BASE_MOVE_FIELDS,
    MAX_ACCOUNT_LINES,
    _extract_request,
    _many2one_id,
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


def try_hybrid_account_partner_search(
    payload: ChatSpreadsheetRequest,
    db_session: Session,
) -> dict[str, Any] | None:
    extracted = _extract_request(payload.prompt or "")
    if not extracted:
        return None

    account_code, search_term = extracted

    try:
        matcher = get_local_name_matcher()
        model_version = matcher.model_version
        match_threshold = matcher.accept_threshold
    except Exception:
        # Runtime scoring still has a conservative dependency-free fallback.
        model_version = "fallback"
        match_threshold = 0.80

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

        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [[["code", "=", account_code]]],
            {
                "fields": ["id", "code", "name"],
                "limit": 50,
            },
        )

        if not accounts:
            return {
                "message": f"لم أجد الحساب {account_code} داخل Odoo.",
                "grid_data": [header],
                "intent": "hybrid_account_partner_search",
                "account_code": account_code,
                "search_term": search_term,
                "model_version": model_version,
            }

        account_ids = [
            account["id"]
            for account in accounts
            if isinstance(account.get("id"), int)
        ]
        account_names = {
            account["id"]: _value_text(account.get("name"))
            for account in accounts
            if isinstance(account.get("id"), int)
        }

        line_metadata = _read_fields(erp, "account.move.line")
        move_metadata = _read_fields(erp, "account.move")
        line_fields = _select_fields(line_metadata, BASE_LINE_FIELDS)
        move_fields = _select_fields(move_metadata, BASE_MOVE_FIELDS)

        domain: list[Any] = [["account_id", "in", account_ids]]
        if payload.company_id:
            domain.append(["company_id", "=", int(payload.company_id)])

        lines, total_account_lines, truncated = _read_account_lines(
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
        moves = _read_moves(erp, move_ids, move_fields)

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
                result = explain_similarity(search_term, value)

                if best_result is None or result.score > best_result.score:
                    best_result = result
                    best_field = f"account.move.line.{field_name}"
                    best_value = value

            for field_name in move_fields:
                value = _value_text(move.get(field_name))
                result = explain_similarity(search_term, value)

                if best_result is None or result.score > best_result.score:
                    best_result = result
                    best_field = f"account.move.{field_name}"
                    best_value = value

            if best_result is None or best_result.decision != "match":
                continue

            account_id = _many2one_id(line.get("account_id"))
            account_label = _value_text(line.get("account_id"))
            account_name = account_names.get(account_id or -1) or account_label
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
                "✅ تم البحث مباشرة في Odoo باستخدام نموذج محلي هجين "
                "دون إرسال البيانات إلى أي مزود ذكاء اصطناعي خارجي. "
                f"وجدت {matched_count} حركة على الحساب {account_code} مرتبطة "
                f"بالكلمة «{search_term}» أو كتابة قريبة موثوقة منها."
            )
        else:
            message = (
                f"لم أجد حركات مؤكدة على الحساب {account_code} تطابق الكلمة "
                f"«{search_term}» بعد التحقق بالنموذج المحلي الهجين."
            )

        message += f"\nتم فحص {len(lines)} من أصل {total_account_lines} سطر حساب."

        if truncated:
            message += (
                f"\n⚠️ عدد السطور تجاوز حد الأمان {MAX_ACCOUNT_LINES}؛ "
                "تم فحص أول جزء فقط."
            )

        return {
            "message": message,
            "grid_data": rows,
            "active_sheet_name": f"{account_code} - {search_term}",
            "intent": "hybrid_account_partner_search",
            "account_code": account_code,
            "search_term": search_term,
            "matched_count": matched_count,
            "scanned_count": len(lines),
            "total_account_lines": total_account_lines,
            "truncated": truncated,
            "model_version": model_version,
            "match_threshold": match_threshold,
        }

    except Exception:
        logger.exception("Hybrid Odoo account/partner search failed.")
        return {
            "message": (
                "فهمت طلب البحث بالحساب والشريك، لكن تعذر تنفيذ البحث المباشر "
                "في Odoo. تحقق من اتصال Odoo وصلاحيات قراءة القيود."
            ),
            "grid_data": None,
            "intent": "hybrid_account_partner_search",
            "account_code": account_code,
            "search_term": search_term,
            "model_version": model_version,
        }
