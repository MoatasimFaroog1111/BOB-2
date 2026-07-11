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
from app.api.v1.erp import ChatSpreadsheetRequest
from app.db.database import get_db

router = APIRouter()

WRITE_INTENT_TERMS_AR = [
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
    "ترحيل",
    "ترحل",
    "رحل",
    "اعتماد",
    "اعتمد",
    "تعتمد",
    "تسجيل في اودو",
    "تسجيل في أودو",
]

WRITE_INTENT_TERMS_EN = [
    "edit",
    "modify",
    "update",
    "change",
    "correct",
    "fix",
    "delete",
    "remove",
    "cancel",
    "reverse",
    "post",
    "approve",
    "submit to odoo",
]

ENTRY_CONTEXT_TERMS_AR = [
    "قيد",
    "القيد",
    "قيود",
    "القيود",
    "هذه القيود",
    "كل القيود",
    "القيود الموجودة",
    "أودو",
    "اودو",
    "odoo",
]

ENTRY_CONTEXT_TERMS_EN = [
    "entry",
    "entries",
    "journal",
    "move",
    "moves",
    "odoo",
    "these entries",
    "all entries",
]

DATE_TERMS_AR = ["تاريخ", "التاريخ", "تايخ", "التايخ"]
DATE_TERMS_EN = ["date", "dated"]
QUESTION_TERMS_AR = ["هل", "تستطيع", "يمكنك", "هل يمكن", "ممكن", "تقدر", "هل اقدر", "هل أقدر"]
QUESTION_TERMS_EN = ["can", "could", "are you able", "do you", "is it possible"]

DATE_DMY_PATTERN = re.compile(r"\b([0-3]?\d)[/-]([01]?\d)[/-]((?:19|20)\d{2})\b")
DATE_ISO_PATTERN = re.compile(r"\b((?:19|20)\d{2})-([01]?\d)-([0-3]?\d)\b")


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _normal_text(prompt: str) -> str:
    return (prompt or "").strip().lower()


def _has_write_term(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, WRITE_INTENT_TERMS_AR) or _contains_any(text, WRITE_INTENT_TERMS_EN)


def _has_entry_context(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, ENTRY_CONTEXT_TERMS_AR) or _contains_any(text, ENTRY_CONTEXT_TERMS_EN)


def _has_question_marker(prompt: str) -> bool:
    text = _normal_text(prompt)
    return "؟" in text or "?" in text or _contains_any(text, QUESTION_TERMS_AR) or _contains_any(text, QUESTION_TERMS_EN)


def _has_date_term(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _contains_any(text, DATE_TERMS_AR) or _contains_any(text, DATE_TERMS_EN)


def _looks_like_odoo_write_intent(prompt: str) -> bool:
    """Detect real Odoo-entry write intent, not generic spreadsheet formatting questions.

    The grid may already contain entry numbers, so a generic question such as
    "هل تستطيع تعديل عرض الأعمدة؟" must not be treated as an Odoo journal edit.
    Therefore a write term must also be tied to journal-entry context in the prompt.
    """
    text = _normal_text(prompt)
    if not text or not _has_write_term(text):
        return False

    if not _has_entry_context(text):
        return False

    command_starters = (
        "عدل",
        "غيّر",
        "غير",
        "صحح",
        "احذف",
        "اعكس",
        "رحل",
        "اعتمد",
        "اريد",
        "أريد",
        "ابغى",
        "عايز",
    )

    # Questions and direct commands are both edit intent; they should not fall through
    # to the read-only Odoo lookup just because the sheet contains entry numbers.
    return _has_question_marker(text) or text.startswith(command_starters) or _has_date_change_intent(text)


def _has_date_change_intent(prompt: str) -> bool:
    text = _normal_text(prompt)
    return _has_write_term(text) and _has_date_term(text) and _has_entry_context(text)


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
        if any(cell in {"رقم القيد", "entry number", "journal entry", "move"} for cell in normalized_cells) and any(
            cell in {"التاريخ", "date"} for cell in normalized_cells
        ):
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
    references: list[str],
    move_ids: list[int],
    iso_date: str,
    display_date: str,
) -> dict[str, Any]:
    grid_data, changed_count, sheet_name = _prepare_date_change_grid(payload, iso_date)

    if arabic:
        if changed_count:
            message = (
                f"فهمت قصدك: تريد تغيير تاريخ كل القيود الظاهرة في الجدول إلى {display_date}.\n\n"
                f"جهزت مسودة التعديل داخل الجدول وعدّلت عمود التاريخ إلى {iso_date} لعدد {changed_count} سطر مرتبط بقيود.\n\n"
                "لم أكتب أي تعديل داخل Odoo مباشرة. راجع الجدول أولًا، وبعد التأكد استخدم زر تسجيل/اعتماد التعديل فقط إذا كان هذا هو المطلوب."
            )
        else:
            message = (
                f"فهمت أنك تريد تغيير تاريخ القيود إلى {display_date}، لكن لم أجد صفوف قيود واضحة داخل الجدول الحالي لتعديل تاريخها."
            )
    else:
        if changed_count:
            message = (
                f"Understood: you want to change the date of the entries shown in the sheet to {display_date}.\n\n"
                f"I prepared a draft update in the sheet and set the date column to {iso_date} for {changed_count} journal-entry line(s).\n\n"
                "I did not write anything to Odoo directly. Review the sheet first, then use the submit/approve action only if this is intended."
            )
        else:
            message = f"I understood the target date {display_date}, but I could not find clear journal-entry rows in the current sheet."

    return {
        "message": message,
        "grid_data": grid_data,
        "active_sheet_name": "مسودة تعديل تاريخ القيود" if arabic else "Draft Entry Date Change",
        "intent": "odoo_entry_date_change_draft",
        "target_date": iso_date,
        "changed_rows": changed_count,
        "source_sheet_name": sheet_name,
        "detected_entry_numbers": references,
        "detected_move_ids": move_ids,
    }


def _write_intent_answer(arabic: bool, references: list[str], move_ids: list[int]) -> dict[str, Any]:
    if arabic:
        message = (
            "فهمت قصدك: هذا طلب تعديل على القيود الموجودة، وليس طلب جلب القيود مرة ثانية.\n\n"
            "أستطيع تجهيز التعديل المقترح للقيود الظاهرة في الجدول، لكن لا أعدّل أو أرحّل داخل Odoo مباشرة بدون مراجعة واعتماد واضح.\n\n"
            "اكتب نوع التعديل بدقة مثل: غيّر التاريخ إلى 31/12/2023، أو غيّر الحساب إلى 104041، وسأجهز المسودة في الجدول بدل جلب القيود من جديد."
        )
    else:
        message = (
            "Understood: this is an edit request for the entries already shown, not a request to fetch them again.\n\n"
            "I can prepare a proposed edit in the sheet, but I will not modify or post anything in Odoo without a clear reviewed approval."
        )

    return {
        "message": message,
        "grid_data": None,
        "intent": "odoo_entry_write_or_edit_request",
        "detected_entry_numbers": references,
        "detected_move_ids": move_ids,
    }


@router.post("/chat-spreadsheet")
def guarded_chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    prompt = payload.prompt or ""
    collected_text = _collect_payload_text(payload)
    all_references, all_move_ids = extract_journal_entry_numbers(collected_text)
    prompt_references, prompt_move_ids = extract_journal_entry_numbers(prompt)
    has_visible_entries = bool(all_references or all_move_ids or prompt_references or prompt_move_ids)

    if has_visible_entries and _looks_like_odoo_write_intent(prompt):
        parsed_date = _parse_target_date(prompt)
        if parsed_date and _has_date_change_intent(prompt):
            iso_date, display_date = parsed_date
            return _date_change_answer(
                _is_arabic(prompt),
                payload,
                all_references,
                all_move_ids,
                iso_date,
                display_date,
            )
        return _write_intent_answer(_is_arabic(prompt), all_references, all_move_ids)

    return chat_spreadsheet_with_odoo_entry_lookup(payload=payload, db_session=db_session)
