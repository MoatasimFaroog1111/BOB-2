import re
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.chat_journal_lookup import (
    _collect_payload_text,
    _is_arabic,
    chat_spreadsheet_with_odoo_entry_lookup,
    extract_journal_entry_numbers,
)
from app.api.v1.erp import ChatSpreadsheetRequest, chat_spreadsheet as legacy_chat_spreadsheet
from app.db.database import get_db

router = APIRouter()

# Action schema used by this deterministic intent router. The assistant should not
# infer "found entry numbers = fetch from Odoo" anymore. It must first route the
# user's prompt into one of these actions.
ACTION_SCHEMA = {
    "intent": [
        "fetch_entries",
        "prepare_bulk_update",
        "capability_question",
        "post_requires_confirmation",
        "legacy_chat",
        "clarify",
    ],
    "target": ["prompt_entries", "current_table_entries", "none"],
    "field": ["date", "account", "partner", "label", "unknown"],
    "requires_confirmation": "boolean",
}

FETCH_TERMS_AR = [
    "اجلب",
    "جلب",
    "هات",
    "اعرض",
    "عرض",
    "اظهر",
    "أظهر",
    "افتح",
    "فتح",
    "اقرأ",
    "إقرأ",
    "قراءة",
    "تفاصيل",
    "تفصيل",
    "بيانات",
    "استخرج",
]
FETCH_TERMS_EN = ["fetch", "get", "show", "display", "open", "read", "lookup", "details", "extract"]

WRITE_TERMS_AR = [
    "تعديل",
    "التعديل",
    "تعدل",
    "أعدل",
    "اعدل",
    "عدل",
    "تغيير",
    "تغير",
    "غيّر",
    "غير",
    "اجعل",
    "أجعل",
    "خلي",
    "خلّي",
    "بدل",
    "استبدل",
    "تصحيح",
    "صحح",
    "تصحح",
    "حذف",
    "احذف",
    "تحذف",
    "إلغاء",
    "الغاء",
    "تلغي",
    "عكس",
    "اعكس",
    "عكسها",
]
WRITE_TERMS_EN = ["edit", "modify", "update", "change", "set", "make", "correct", "fix", "delete", "remove", "cancel", "reverse"]

POST_TERMS_AR = ["ترحيل", "ترحل", "رحل", "اعتماد", "اعتمد", "تعتمد", "تسجيل في اودو", "تسجيل في أودو", "سجل في اودو", "سجل في أودو"]
POST_TERMS_EN = ["post", "approve", "submit to odoo", "write to odoo", "commit to odoo"]

ENTRY_CONTEXT_TERMS_AR = ["قيد", "القيد", "قيود", "القيود", "هذه القيود", "كل القيود", "القيود الموجودة", "أودو", "اودو", "odoo"]
ENTRY_CONTEXT_TERMS_EN = ["entry", "entries", "journal", "move", "moves", "odoo", "these entries", "all entries"]

DATE_TERMS_AR = ["تاريخ", "التاريخ", "تايخ", "التايخ"]
DATE_TERMS_EN = ["date", "dated"]
ACCOUNT_TERMS_AR = ["حساب", "الحساب", "كود الحساب", "رمز الحساب"]
ACCOUNT_TERMS_EN = ["account", "account code"]
PARTNER_TERMS_AR = ["شريك", "الشريك", "عميل", "مورد"]
PARTNER_TERMS_EN = ["partner", "customer", "vendor", "supplier"]
LABEL_TERMS_AR = ["بيان", "البيان", "وصف", "الوصف"]
LABEL_TERMS_EN = ["label", "description", "memo", "narration"]

QUESTION_TERMS_AR = ["هل", "تستطيع", "يمكنك", "هل يمكن", "ممكن", "تقدر", "هل اقدر", "هل أقدر"]
QUESTION_TERMS_EN = ["can", "could", "are you able", "do you", "is it possible"]

DATE_DMY_PATTERN = re.compile(r"\b([0-3]?\d)[/-]([01]?\d)[/-]((?:19|20)\d{2})\b")
DATE_ISO_PATTERN = re.compile(r"\b((?:19|20)\d{2})-([01]?\d)-([0-3]?\d)\b")


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _normal_text(prompt: str) -> str:
    return (prompt or "").strip().lower()


def _has_fetch_term(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, FETCH_TERMS_AR) or _contains_any(text, FETCH_TERMS_EN)


def _has_write_term(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, WRITE_TERMS_AR) or _contains_any(text, WRITE_TERMS_EN)


def _has_post_term(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, POST_TERMS_AR) or _contains_any(text, POST_TERMS_EN)


def _has_entry_context(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, ENTRY_CONTEXT_TERMS_AR) or _contains_any(text, ENTRY_CONTEXT_TERMS_EN)


def _has_question_marker(prompt: str) -> bool:
    text = _normal_text(prompt)
    return "؟" in text or "?" in text or _contains_any(text, QUESTION_TERMS_AR) or _contains_any(text, QUESTION_TERMS_EN)


def _has_date_term(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, DATE_TERMS_AR) or _contains_any(text, DATE_TERMS_EN)


def _infer_field(prompt: str) -> str:
    text = _normal_text(prompt)
    if _contains_any(text, DATE_TERMS_AR) or _contains_any(text, DATE_TERMS_EN) or _parse_target_date(prompt):
        return "date"
    if _contains_any(text, ACCOUNT_TERMS_AR) or _contains_any(text, ACCOUNT_TERMS_EN):
        return "account"
    if _contains_any(text, PARTNER_TERMS_AR) or _contains_any(text, PARTNER_TERMS_EN):
        return "partner"
    if _contains_any(text, LABEL_TERMS_AR) or _contains_any(text, LABEL_TERMS_EN):
        return "label"
    return "unknown"


def _parse_target_date(prompt: str) -> tuple[str, str] | None:
    text = (prompt or "").strip()

    dmy = DATE_DMY_PATTERN.search(text)
    if dmy:
        day = int(dmy.group(1))
        month = int(dmy.group(2))
        year = int(dmy.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-{day:02d}", f"{day:02d}/{month:02d}/{year:04d}"

    iso = DATE_ISO_PATTERN.search(text)
    if iso:
        year = int(iso.group(1))
        month = int(iso.group(2))
        day = int(iso.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-{day:02d}", f"{day:02d}/{month:02d}/{year:04d}"

    return None


def _sheet_rows(payload: ChatSpreadsheetRequest) -> tuple[str, list[list[Any]]]:
    for sheet in payload.sheets or []:
        if sheet.gridData:
            return sheet.name or "", [list(row) for row in sheet.gridData]
    return "", []


def _find_header_row(grid: list[list[Any]]) -> int:
    for idx, row in enumerate(grid[:10]):
        normalized_cells = [str(cell or "").strip().lower() for cell in row]
        has_entry_header = any(cell in {"رقم القيد", "entry number", "journal entry", "move"} for cell in normalized_cells)
        has_date_header = any(cell in {"التاريخ", "date"} for cell in normalized_cells)
        if has_entry_header and has_date_header:
            return idx
    return 0


def _find_column_index(header: list[Any], candidates: set[str], fallback: int) -> int:
    for idx, cell in enumerate(header):
        normalized = str(cell or "").strip().lower()
        if normalized in candidates:
            return idx
    return fallback


def _row_has_entry_reference(row: list[Any]) -> bool:
    references, move_ids = extract_journal_entry_numbers(" ".join(str(cell or "") for cell in row))
    return bool(references or move_ids)


def _current_table_has_entries(payload: ChatSpreadsheetRequest) -> bool:
    _, grid = _sheet_rows(payload)
    if not grid:
        return False
    return any(_row_has_entry_reference(row) for row in grid[:1000])


def _router_state(payload: ChatSpreadsheetRequest, prompt: str) -> dict[str, Any]:
    sheet_name, grid = _sheet_rows(payload)
    prompt_references, prompt_move_ids = extract_journal_entry_numbers(prompt)
    sheet_references, sheet_move_ids = extract_journal_entry_numbers("\n".join(" ".join(str(cell or "") for cell in row) for row in grid))
    return {
        "sheet_name": sheet_name,
        "has_current_table_entries": bool(sheet_references or sheet_move_ids or _current_table_has_entries(payload)),
        "prompt_references": prompt_references,
        "prompt_move_ids": prompt_move_ids,
        "sheet_references": sheet_references,
        "sheet_move_ids": sheet_move_ids,
    }


def _classify_action(prompt: str, state: dict[str, Any]) -> dict[str, Any]:
    text = _normal_text(prompt)
    prompt_has_refs = bool(state["prompt_references"] or state["prompt_move_ids"])
    table_has_entries = bool(state["has_current_table_entries"])
    field = _infer_field(prompt)

    if not text:
        return {"intent": "legacy_chat", "target": "none", "field": "unknown", "requires_confirmation": False}

    # Explicit fetch/read/show commands are the only path that may call Odoo lookup.
    if _has_fetch_term(text):
        return {
            "intent": "fetch_entries",
            "target": "prompt_entries" if prompt_has_refs else "current_table_entries",
            "field": "unknown",
            "requires_confirmation": False,
        }

    # Pasting one or more entry references without another action is treated as a fetch request.
    if prompt_has_refs and not _has_write_term(text) and not _has_post_term(text) and not _has_question_marker(text):
        return {"intent": "fetch_entries", "target": "prompt_entries", "field": "unknown", "requires_confirmation": False}

    # Posting/approving/writing to Odoo is never performed by this route.
    if _has_post_term(text) and (prompt_has_refs or table_has_entries or _has_entry_context(text)):
        return {
            "intent": "post_requires_confirmation",
            "target": "prompt_entries" if prompt_has_refs else "current_table_entries",
            "field": field,
            "requires_confirmation": True,
        }

    # Capability questions should be answered, not executed and not fetched.
    if _has_question_marker(text) and (_has_write_term(text) or _has_post_term(text)):
        return {
            "intent": "capability_question",
            "target": "current_table_entries" if table_has_entries else "prompt_entries" if prompt_has_refs else "none",
            "field": field,
            "requires_confirmation": True,
        }

    # Any edit/change command against an already displayed Odoo-entry table is a draft update.
    # This is the important fix for prompts like: "غيّر التاريخ إلى 31/12/2023".
    if table_has_entries and (_has_write_term(text) or _parse_target_date(text)):
        return {
            "intent": "prepare_bulk_update",
            "target": "current_table_entries",
            "field": field,
            "requires_confirmation": True,
        }

    # Edit commands with explicit entry references are also draft updates, not read-only fetches.
    if prompt_has_refs and (_has_write_term(text) or _parse_target_date(text)):
        return {
            "intent": "prepare_bulk_update",
            "target": "prompt_entries",
            "field": field,
            "requires_confirmation": True,
        }

    # If the user mentions entries and an edit verb but the target is unclear, do not fetch.
    if _has_entry_context(text) and _has_write_term(text):
        return {
            "intent": "clarify",
            "target": "current_table_entries" if table_has_entries else "none",
            "field": field,
            "requires_confirmation": True,
        }

    return {"intent": "legacy_chat", "target": "none", "field": "unknown", "requires_confirmation": False}


def _prepare_date_change_grid(payload: ChatSpreadsheetRequest, iso_date: str) -> tuple[list[list[Any]] | None, int, str | None]:
    sheet_name, grid = _sheet_rows(payload)
    if not grid:
        return None, 0, sheet_name

    header_row_idx = _find_header_row(grid)
    header = grid[header_row_idx] if header_row_idx < len(grid) else []
    date_col = _find_column_index(header, {"التاريخ", "date"}, 1)
    entry_col = _find_column_index(header, {"رقم القيد", "entry number", "journal entry", "move"}, 0)

    max_width = max(max((len(row) for row in grid), default=0), date_col + 1, entry_col + 1)
    changed_count = 0

    for row_idx in range(header_row_idx + 1, len(grid)):
        row = grid[row_idx]
        if len(row) < max_width:
            row.extend([""] * (max_width - len(row)))

        has_entry = bool(str(row[entry_col] or "").strip()) or _row_has_entry_reference(row)
        if not has_entry:
            continue

        row[date_col] = iso_date
        changed_count += 1

    return grid, changed_count, sheet_name


def _date_change_answer(
    arabic: bool,
    payload: ChatSpreadsheetRequest,
    state: dict[str, Any],
    action: dict[str, Any],
    iso_date: str,
    display_date: str,
) -> dict[str, Any]:
    grid_data, changed_count, sheet_name = _prepare_date_change_grid(payload, iso_date)

    if arabic:
        if changed_count:
            message = (
                f"فهمت قصدك: تريد تغيير تاريخ القيود الموجودة حاليًا في الجدول إلى {display_date}.\n\n"
                f"جهزت مسودة التعديل داخل الجدول وعدّلت عمود التاريخ إلى {iso_date} لعدد {changed_count} سطر مرتبط بقيود.\n\n"
                "لم أكتب أي تعديل داخل Odoo مباشرة. راجع الجدول أولًا، ثم استخدم زر الاعتماد/التسجيل فقط بعد التأكد."
            )
        else:
            message = f"فهمت أنك تريد تغيير التاريخ إلى {display_date}، لكن لم أجد صفوف قيود واضحة داخل الجدول الحالي."
    else:
        if changed_count:
            message = (
                f"Understood: you want to change the date of the entries currently shown in the sheet to {display_date}.\n\n"
                f"I prepared a draft update in the sheet and set the date column to {iso_date} for {changed_count} journal-entry line(s).\n\n"
                "I did not write anything to Odoo directly. Review the sheet first, then approve/submit only if intended."
            )
        else:
            message = f"I understood the target date {display_date}, but I could not find clear journal-entry rows in the current sheet."

    return {
        "message": message,
        "grid_data": grid_data,
        "active_sheet_name": "مسودة تعديل تاريخ القيود" if arabic else "Draft Entry Date Change",
        "intent": action["intent"],
        "action": action,
        "target_date": iso_date,
        "changed_rows": changed_count,
        "source_sheet_name": sheet_name,
        "detected_entry_numbers": state["sheet_references"] or state["prompt_references"],
        "detected_move_ids": state["sheet_move_ids"] or state["prompt_move_ids"],
    }


def _edit_request_answer(arabic: bool, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    field = action.get("field") or "unknown"
    if arabic:
        if field == "unknown":
            message = (
                "فهمت أن هذا طلب تعديل على القيود الحالية، وليس طلب جلب من Odoo.\n\n"
                "حدد الحقل والقيمة المطلوبة بوضوح، مثل: غيّر التاريخ إلى 31/12/2023، أو غيّر الحساب إلى 104041. "
                "بعدها سأجهز مسودة التعديل داخل الجدول للمراجعة، بدون كتابة مباشرة في Odoo."
            )
        else:
            message = (
                f"فهمت أن هذا طلب تعديل على حقل {field} للقيود الحالية.\n\n"
                "لم أنفذ كتابة مباشرة في Odoo. أرسل القيمة الجديدة بوضوح وسأجهزها كمسودة في الجدول للمراجعة."
            )
    else:
        message = (
            "Understood: this is an edit request for the current entries, not an Odoo fetch request. "
            "Please specify the exact field and new value, and I will prepare a reviewable draft in the sheet without writing directly to Odoo."
        )

    return {
        "message": message,
        "grid_data": None,
        "intent": action["intent"],
        "action": action,
        "detected_entry_numbers": state["sheet_references"] or state["prompt_references"],
        "detected_move_ids": state["sheet_move_ids"] or state["prompt_move_ids"],
    }


def _capability_or_confirmation_answer(arabic: bool, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    if arabic:
        if action["intent"] == "post_requires_confirmation":
            message = (
                "هذا طلب قد يكتب أو يرحّل داخل Odoo، لذلك لن أنفذه مباشرة من التشات.\n\n"
                "أستطيع تجهيز مسودة واضحة ثم أطلب اعتمادًا صريحًا قبل أي كتابة في Odoo."
            )
        else:
            message = (
                "نعم، أستطيع تجهيز تعديلات مقترحة على القيود الموجودة في الجدول مثل التاريخ أو الحساب أو الشريك أو البيان.\n\n"
                "لكن أي كتابة فعلية في Odoo يجب أن تمر كمراجعة واعتماد واضح، وليس تلقائيًا بمجرد وجود أرقام قيود."
            )
    else:
        message = (
            "Yes, I can prepare proposed changes for the entries shown in the sheet. "
            "Any actual write to Odoo must remain reviewed and explicitly approved."
        )

    return {
        "message": message,
        "grid_data": None,
        "intent": action["intent"],
        "action": action,
        "detected_entry_numbers": state["sheet_references"] or state["prompt_references"],
        "detected_move_ids": state["sheet_move_ids"] or state["prompt_move_ids"],
    }


@router.post("/chat-spreadsheet")
def guarded_chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    prompt = payload.prompt or ""
    arabic = _is_arabic(prompt)
    state = _router_state(payload, prompt)
    action = _classify_action(prompt, state)

    if action["intent"] == "fetch_entries":
        return chat_spreadsheet_with_odoo_entry_lookup(payload=payload, db_session=db_session)

    if action["intent"] == "prepare_bulk_update":
        parsed_date = _parse_target_date(prompt)
        if action.get("field") == "date" and parsed_date:
            iso_date, display_date = parsed_date
            return _date_change_answer(arabic, payload, state, action, iso_date, display_date)
        return _edit_request_answer(arabic, state, action)

    if action["intent"] in {"capability_question", "post_requires_confirmation"}:
        return _capability_or_confirmation_answer(arabic, state, action)

    if action["intent"] == "clarify":
        return _edit_request_answer(arabic, state, action)

    # Default: do not call the Odoo lookup just because the current sheet contains
    # journal entry numbers. Only the explicit fetch_entries action may do that.
    return legacy_chat_spreadsheet(payload=payload, db_session=db_session)
