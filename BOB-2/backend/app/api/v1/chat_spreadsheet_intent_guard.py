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

QUESTION_TERMS_AR = ["هل", "تستطيع", "يمكنك", "هل يمكن", "ممكن", "تقدر", "هل اقدر", "هل أقدر"]
QUESTION_TERMS_EN = ["can", "could", "are you able", "do you", "is it possible"]


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _looks_like_odoo_write_intent(prompt: str) -> bool:
    text = (prompt or "").strip().lower()
    if not text:
        return False

    has_write_term = _contains_any(text, WRITE_INTENT_TERMS_AR) or _contains_any(text, WRITE_INTENT_TERMS_EN)
    if not has_write_term:
        return False

    has_question_marker = (
        "؟" in text
        or "?" in text
        or _contains_any(text, QUESTION_TERMS_AR)
        or _contains_any(text, QUESTION_TERMS_EN)
    )

    # Even if it is written as a command, do not let the lookup layer pretend it edited entries.
    return has_question_marker or text.startswith(("عدل", "غيّر", "غير", "صحح", "احذف", "اعكس", "رحل", "اعتمد"))


def _write_intent_answer(arabic: bool, references: list[str], move_ids: list[int]) -> dict[str, Any]:
    if arabic:
        message = (
            "أفهم سؤالك. نعم أستطيع مساعدتك في مراجعة هذه القيود وتجهيز التعديل المقترح، "
            "مثل تغيير الحساب، الشريك، البيان، أو تجهيز قيد عكسي/تصحيحي.\n\n"
            "لكن هذا التشات لا يجب أن يعدّل أو يرحّل قيود Odoo مباشرة بمجرد وجود أرقام قيود؛ "
            "لا بد أن تحدد نوع التعديل المطلوب بوضوح ثم يتم عرضه للمراجعة قبل أي إجراء.\n\n"
            "اكتب مثلًا: عدّل الحساب في القيد MISC/2024/12/0040 إلى 104041، "
            "أو جهّز قيد عكسي لهذه القيود، وسأرتب لك التعديل المقترح بشكل واضح."
        )
    else:
        message = (
            "I understand the question. I can help review these entries and prepare a proposed edit, "
            "such as changing the account, partner, label, or preparing a reversal/correction entry.\n\n"
            "However, the smart chat should not modify or post Odoo entries just because entry numbers are present. "
            "Please specify the exact change required, and I will prepare it for review before any action."
        )

    return {
        "message": message,
        "grid_data": None,
        "intent": "odoo_entry_write_or_edit_question",
        "detected_entry_numbers": references,
        "detected_move_ids": move_ids,
    }


@router.post("/chat-spreadsheet")
def guarded_chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    collected_text = _collect_payload_text(payload)
    references, move_ids = extract_journal_entry_numbers(collected_text)

    if (references or move_ids) and _looks_like_odoo_write_intent(payload.prompt):
        return _write_intent_answer(_is_arabic(payload.prompt), references, move_ids)

    return chat_spreadsheet_with_odoo_entry_lookup(payload=payload, db_session=db_session)
