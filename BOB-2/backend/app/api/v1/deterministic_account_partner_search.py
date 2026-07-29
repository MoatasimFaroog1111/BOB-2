"""Deterministic Odoo search by account code and multilingual text.

This module performs read-only searches directly against Odoo without requiring
Anthropic, Ollama, or any other language-model provider.
"""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.erp import ChatSpreadsheetRequest
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value
from app.security.tenant_scope import current_organization_id


MAX_ACCOUNT_LINES = 20_000
SEARCH_BATCH_SIZE = 500
MATCH_THRESHOLD = 0.72

FETCH_TERMS = (
    "اجلب",
    "جلب",
    "احضر",
    "أحضر",
    "هات",
    "اعرض",
    "أعرض",
    "اظهر",
    "أظهر",
    "استخرج",
    "ابحث",
    "بحث",
    "fetch",
    "get",
    "show",
    "display",
    "find",
    "search",
)

ACCOUNT_PATTERN = re.compile(
    r"(?:رمز\s*الحساب|كود\s*الحساب|رقم\s*الحساب|الحساب|حساب|"
    r"account\s*code|account\s*(?:number|no\.?)?|account)"
    r"\s*[:#=\-–—]?\s*([0-9٠-٩][0-9٠-٩.\-]{3,20})",
    re.IGNORECASE,
)

SEARCH_TERM_PATTERN = re.compile(
    r"(?:اسم\s*الشريك|الشريك|شريك|اسم\s*المورد|المورد|مورد|"
    r"اسم\s*العميل|العميل|عميل|الكلمة|كلمة|"
    r"partner(?:\s*name)?|vendor(?:\s*name)?|supplier(?:\s*name)?|"
    r"customer(?:\s*name)?|word|term)"
    r"\s*(?:اسمه|اسم|name)?\s*[:#=\-–—]?\s*[\"']?"
    r"([^,\n،;؛]+)",
    re.IGNORECASE,
)

STOP_WORDS = {
    "كل",
    "ما",
    "يتعلق",
    "المتعلق",
    "المرتبطة",
    "المرتبط",
    "قريب",
    "قريبة",
    "منها",
    "منه",
    "سواء",
    "سوى",
    "في",
    "داخل",
    "باللغة",
    "بالعربية",
    "بالانجليزية",
    "بالإنجليزية",
    "العربية",
    "الانجليزية",
    "الإنجليزية",
    "او",
    "أو",
    "و",
    "and",
    "or",
    "all",
    "related",
    "anything",
    "everything",
    "similar",
    "approximately",
}

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

ARABIC_TO_LATIN = {
    "ا": "a",
    "أ": "a",
    "إ": "i",
    "آ": "a",
    "ء": "a",
    "ؤ": "o",
    "ئ": "e",
    "ب": "b",
    "ت": "t",
    "ث": "th",
    "ج": "j",
    "ح": "h",
    "خ": "kh",
    "د": "d",
    "ذ": "th",
    "ر": "r",
    "ز": "z",
    "س": "s",
    "ش": "sh",
    "ص": "s",
    "ض": "d",
    "ط": "t",
    "ظ": "z",
    "ع": "a",
    "غ": "gh",
    "ف": "f",
    "ق": "q",
    "ك": "k",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "ه": "h",
    "ة": "a",
    "و": "w",
    "ي": "y",
    "ى": "a",
}

TEXT_FIELD_HINTS = {
    "name",
    "description",
    "label",
    "memo",
    "narration",
    "reference",
    "ref",
    "payment",
    "communication",
    "partner",
    "customer",
    "vendor",
    "supplier",
    "check",
    "cheque",
    "chq",
    "شيك",
}

TEXT_FIELD_TYPES = {
    "char",
    "text",
    "html",
    "selection",
    "reference",
    "many2one",
}

BASE_LINE_FIELDS = [
    "id",
    "move_id",
    "date",
    "account_id",
    "partner_id",
    "name",
    "ref",
    "debit",
    "credit",
    "balance",
    "company_id",
]

BASE_MOVE_FIELDS = [
    "id",
    "name",
    "date",
    "ref",
    "payment_reference",
    "narration",
    "invoice_origin",
    "partner_id",
    "journal_id",
    "state",
    "move_type",
    "company_id",
]


def _normalize(value: Any) -> str:
    text = str(value or "").translate(ARABIC_DIGITS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower()
    text = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]", "", text)
    text = text.replace("ـ", "")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _transliterate(value: Any) -> str:
    normalized = _normalize(value)
    translated = "".join(ARABIC_TO_LATIN.get(character, character) for character in normalized)
    return re.sub(r"\s+", " ", translated).strip()


def _latin_skeleton(value: str) -> str:
    text = value.lower()
    text = text.replace("ph", "f")
    text = re.sub(r"[aeiou]", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _forms(value: Any) -> set[str]:
    native = _normalize(value)
    latin = _transliterate(value)

    forms = {
        native,
        native.replace(" ", ""),
        latin,
        latin.replace(" ", ""),
        _latin_skeleton(latin),
    }
    return {form for form in forms if form}


def _similarity(query: str, candidate: Any) -> float:
    candidate_text = str(candidate or "").strip()
    if not candidate_text:
        return 0.0

    query_forms = _forms(query)
    candidate_forms = _forms(candidate_text)

    best = 0.0

    for query_form in query_forms:
        for candidate_form in candidate_forms:
            if min(len(query_form), len(candidate_form)) >= 3 and (
                query_form in candidate_form or candidate_form in query_form
            ):
                best = max(best, 1.0)
            else:
                best = max(
                    best,
                    SequenceMatcher(None, query_form, candidate_form).ratio(),
                )

    query_tokens = _normalize(query).split()
    candidate_tokens = _normalize(candidate_text).split()

    if query_tokens and candidate_tokens:
        token_scores: list[float] = []

        for query_token in query_tokens:
            query_token_forms = _forms(query_token)
            token_best = 0.0

            for candidate_token in candidate_tokens:
                candidate_token_forms = _forms(candidate_token)

                for query_form in query_token_forms:
                    for candidate_form in candidate_token_forms:
                        if min(len(query_form), len(candidate_form)) >= 3 and (
                            query_form in candidate_form
                            or candidate_form in query_form
                        ):
                            token_best = max(token_best, 1.0)
                        else:
                            token_best = max(
                                token_best,
                                SequenceMatcher(
                                    None,
                                    query_form,
                                    candidate_form,
                                ).ratio(),
                            )

            token_scores.append(token_best)

        if token_scores and min(token_scores) >= 0.66:
            best = max(best, sum(token_scores) / len(token_scores))

    return min(best, 1.0)


def _extract_request(prompt: str) -> tuple[str, str] | None:
    normalized_prompt = _normalize(prompt)

    if not any(_normalize(term) in normalized_prompt for term in FETCH_TERMS):
        return None

    account_match = ACCOUNT_PATTERN.search(prompt.translate(ARABIC_DIGITS))
    if not account_match:
        return None

    account_code = account_match.group(1)
    account_code = re.sub(r"[^0-9.\-]", "", account_code).strip(".-")

    if len(re.sub(r"\D", "", account_code)) < 4:
        return None

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

    return account_code, search_term


def _value_text(value: Any) -> str:
    if value in (None, False):
        return ""

    if isinstance(value, (list, tuple)):
        if len(value) > 1:
            return str(value[1] or "")
        if value:
            return str(value[0] or "")
        return ""

    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values() if item)

    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None

    if isinstance(value, int):
        return value

    return None


def _read_fields(erp: Any, model: str) -> dict[str, dict[str, Any]]:
    try:
        result = erp.execute_kw(
            model,
            "fields_get",
            [],
            {"attributes": ["string", "type"]},
        )
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _select_fields(
    metadata: dict[str, dict[str, Any]],
    base_fields: list[str],
) -> list[str]:
    selected: list[str] = ["id"]

    for field_name in base_fields:
        if field_name == "id" or not metadata or field_name in metadata:
            if field_name not in selected:
                selected.append(field_name)

    for field_name, definition in metadata.items():
        field_type = str(definition.get("type") or "")
        label = str(definition.get("string") or "")
        searchable_text = f"{field_name} {label}".lower()

        if field_type not in TEXT_FIELD_TYPES:
            continue

        if not any(hint in searchable_text for hint in TEXT_FIELD_HINTS):
            continue

        if field_name not in selected:
            selected.append(field_name)

        if len(selected) >= 45:
            break

    return selected


def _read_connection(db_session: Session):
    connection = (
        db_session.query(ERPConnection)
        .filter(
            ERPConnection.organization_id
            == current_organization_id(required=True),
            ERPConnection.is_active.is_(True),
        )
        .first()
    )

    if not connection:
        raise RuntimeError("No active ERP connection found.")

    credentials = json.loads(decrypt_value(connection.encrypted_secret_ref))

    erp = get_erp_provider(
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=credentials.get("username"),
        password=credentials.get("password"),
    )

    return connection, erp


def _read_account_lines(
    erp: Any,
    domain: list[Any],
    fields: list[str],
) -> tuple[list[dict[str, Any]], int, bool]:
    try:
        total_count = int(
            erp.execute_kw(
                "account.move.line",
                "search_count",
                [domain],
            )
            or 0
        )
    except Exception:
        total_count = 0

    target_count = min(
        total_count if total_count else MAX_ACCOUNT_LINES,
        MAX_ACCOUNT_LINES,
    )

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

    if not total_count:
        total_count = len(lines)

    return lines, total_count, total_count > len(lines)


def _read_moves(
    erp: Any,
    move_ids: list[int],
    fields: list[str],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}

    for start in range(0, len(move_ids), 200):
        chunk = move_ids[start : start + 200]

        moves = erp.execute_kw(
            "account.move",
            "search_read",
            [[["id", "in", chunk]]],
            {
                "fields": fields,
                "limit": len(chunk),
            },
        )

        for move in moves or []:
            move_id = move.get("id")
            if isinstance(move_id, int):
                result[move_id] = move

    return result


def try_deterministic_account_partner_search(
    payload: ChatSpreadsheetRequest,
    db_session: Session,
) -> dict[str, Any] | None:
    extracted = _extract_request(payload.prompt or "")
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
                "intent": "deterministic_account_partner_search",
                "account_code": account_code,
                "search_term": search_term,
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

            best_score = 0.0
            best_field = ""
            best_value = ""

            for field_name in line_fields:
                value = _value_text(line.get(field_name))
                score = _similarity(search_term, value)

                if score > best_score:
                    best_score = score
                    best_field = f"account.move.line.{field_name}"
                    best_value = value

            for field_name in move_fields:
                value = _value_text(move.get(field_name))
                score = _similarity(search_term, value)

                if score > best_score:
                    best_score = score
                    best_field = f"account.move.{field_name}"
                    best_value = value

            if best_score < MATCH_THRESHOLD:
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

            journal_name = _value_text(move.get("journal_id"))
            state = _value_text(move.get("state"))

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
                    state,
                    journal_name,
                    partner_name,
                    account_code,
                    account_name,
                    _value_text(line.get("name")),
                    str(debit) if debit else "",
                    str(credit) if credit else "",
                    reference,
                    best_field,
                    best_value,
                    f"{best_score:.0%}",
                    odoo_url,
                ]
            )

        matched_count = len(rows) - 1

        if matched_count:
            message = (
                f"✅ تم البحث مباشرة في Odoo دون استخدام مزود ذكاء اصطناعي. "
                f"وجدت {matched_count} حركة على الحساب {account_code} مرتبطة "
                f"بالكلمة «{search_term}» أو كتابة قريبة منها."
            )
        else:
            message = (
                f"لم أجد حركات على الحساب {account_code} تطابق الكلمة "
                f"«{search_term}» أو كتابة قريبة منها ضمن البيانات التي تم فحصها."
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
            "intent": "deterministic_account_partner_search",
            "account_code": account_code,
            "search_term": search_term,
            "matched_count": matched_count,
            "scanned_count": len(lines),
            "total_account_lines": total_account_lines,
            "truncated": truncated,
        }

    except Exception as exc:
        return {
            "message": (
                "فهمت طلب البحث بالحساب والشريك، لكن تعذر تنفيذ البحث المباشر "
                "في Odoo. تحقق من اتصال Odoo وصلاحيات قراءة القيود."
            ),
            "grid_data": None,
            "intent": "deterministic_account_partner_search",
            "account_code": account_code,
            "search_term": search_term,
            "error": str(exc),
        }
