import json
import re
from typing import Any

from app.api.v1.erp import ChatSpreadsheetRequest

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

DATE_DMY_PATTERN = re.compile(r"\b([0-3]?\d)[/-]([01]?\d)[/-]((?:19|20)\d{2})\b")
DATE_ISO_PATTERN = re.compile(r"\b((?:19|20)\d{2})-([01]?\d)-([0-3]?\d)\b")
NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")

ACCOUNTING_ACTION_SCHEMA = {
    "intent": [
        "change_date",
        "change_account",
        "reverse_entries",
        "post_entries",
        "review_entries",
        "balance_entries",
        "format_entries",
        "explain_capability",
        "legacy_chat",
    ],
    "target": ["current_sheet", "selected_entries", "prompt_entries", "unknown"],
    "field": ["date", "account", "partner", "label", "amount", "unknown"],
    "write_policy": ["draft_only", "requires_confirmation", "read_only"],
}

# Explicit fetch/read terms must win over incidental words found inside pasted
# journal-entry descriptions, such as "Reversal of" or "reverse" in Odoo move names.
FETCH_TERMS = [
    "احضر",
    "أحضر",
    "حضر",
    "اجلب",
    "جلب",
    "هات",
    "اعرض",
    "اظهر",
    "أظهر",
    "افتح",
    "فتح",
    "اقرأ",
    "إقرأ",
    "قراءة",
    "تفاصيل",
    "تفصيل",
    "استخرج",
    "fetch",
    "get",
    "show",
    "display",
    "open",
    "read",
    "lookup",
    "details",
    "extract",
]
DATE_TERMS = ["تاريخ", "التاريخ", "تايخ", "التايخ", "date"]
ACCOUNT_TERMS = ["الحساب", "حساب", "رمز الحساب", "كود الحساب", "account"]
PARTNER_TERMS = ["الشريك", "شريك", "عميل", "مورد", "partner", "customer", "vendor"]
LABEL_TERMS = ["البيان", "بيان", "الوصف", "وصف", "description", "label"]
POST_TERMS = ["رحل", "ترحيل", "اعتمد", "اعتماد", "سجل في اودو", "تسجيل في اودو", "post", "approve"]
REVERSE_TERMS = ["اعكس", "عكس", "قيد عكسي", "reverse", "reversal"]
FORMAT_TERMS = ["نسق", "نظم", "رتب", "format", "organize", "clean"]
BALANCE_TERMS = ["وازن", "متوازن", "الفرق", "balance", "balanced"]
CHANGE_TERMS = ["غير", "غيّر", "تغيير", "بدل", "استبدل", "اجعل", "خلي", "عدل", "تعديل", "update", "change", "set"]
CAPABILITY_TERMS = ["هل", "تستطيع", "يمكنك", "ممكن", "can", "could", "able"]


def _normal(value: str) -> str:
    return (value or "").translate(ARABIC_DIGITS).strip().lower()


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _has_explicit_fetch_command(text: str) -> bool:
    # This check intentionally runs before reverse/change/post routing. The user
    # may paste many Odoo move names containing text such as "Reversal of", but
    # the command itself can still be "احضر هذه القيود من أودو".
    return _contains_any(text, FETCH_TERMS)


def _parse_date(prompt: str) -> tuple[str, str] | None:
    text = _normal(prompt)
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


def _find_numeric_value(prompt: str) -> str | None:
    matches = NUMBER_PATTERN.findall(_normal(prompt))
    return matches[-1].replace(",", "") if matches else None


def _sheet_rows(payload: ChatSpreadsheetRequest) -> tuple[str, list[list[str]]]:
    for sheet in payload.sheets or []:
        if sheet.id == payload.active_sheet_id:
            return sheet.name or "", [list(row) for row in sheet.gridData or []]
    if payload.sheets:
        first = payload.sheets[0]
        return first.name or "", [list(row) for row in first.gridData or []]
    return "", []


def _find_header_row(grid: list[list[str]]) -> int:
    for index, row in enumerate(grid[:12]):
        labels = [str(cell or "").strip().lower() for cell in row]
        has_account = any(label in {"رمز الحساب", "account code", "account"} or "حساب" in label for label in labels)
        has_debit = any(label in {"مدين", "debit"} for label in labels)
        has_credit = any(label in {"دائن", "credit"} for label in labels)
        has_date = any(label in {"التاريخ", "date"} for label in labels)
        if (has_debit and has_credit) or (has_account and has_date):
            return index
    return 0


def _find_column(header: list[str], candidates: set[str], contains: list[str], fallback: int) -> int:
    for idx, value in enumerate(header):
        label = str(value or "").strip().lower()
        if label in candidates or any(term in label for term in contains):
            return idx
    return fallback


def _ensure_rectangular(grid: list[list[str]], min_width: int | None = None) -> list[list[str]]:
    width = max([len(row) for row in grid] + [min_width or 0, 1])
    return [list(row) + [""] * (width - len(row)) for row in grid]


def _row_has_data(row: list[str]) -> bool:
    return any(str(cell or "").strip() for cell in row)


def classify_accounting_command(prompt: str, payload: ChatSpreadsheetRequest) -> dict[str, Any]:
    text = _normal(prompt)
    date_value = _parse_date(prompt)

    if not text:
        return {"intent": "legacy_chat", "target": "unknown", "field": "unknown", "write_policy": "read_only"}

    if _has_explicit_fetch_command(text):
        return {"intent": "legacy_chat", "target": "prompt_entries", "field": "unknown", "write_policy": "read_only"}

    if _contains_any(text, CAPABILITY_TERMS) and (_contains_any(text, CHANGE_TERMS) or _contains_any(text, POST_TERMS)):
        return {"intent": "explain_capability", "target": "current_sheet", "field": "unknown", "write_policy": "read_only"}

    if _contains_any(text, POST_TERMS):
        return {"intent": "post_entries", "target": "current_sheet", "field": "unknown", "write_policy": "requires_confirmation"}

    if _contains_any(text, REVERSE_TERMS):
        return {"intent": "reverse_entries", "target": "current_sheet", "field": "unknown", "write_policy": "draft_only"}

    if date_value and (_contains_any(text, CHANGE_TERMS) or _contains_any(text, DATE_TERMS)):
        return {
            "intent": "change_date",
            "target": "current_sheet",
            "field": "date",
            "value": date_value[0],
            "display_value": date_value[1],
            "write_policy": "draft_only",
        }

    if _contains_any(text, ACCOUNT_TERMS) and _contains_any(text, CHANGE_TERMS):
        return {
            "intent": "change_account",
            "target": "current_sheet",
            "field": "account",
            "value": _find_numeric_value(prompt),
            "write_policy": "draft_only",
        }

    if _contains_any(text, BALANCE_TERMS):
        return {"intent": "balance_entries", "target": "current_sheet", "field": "amount", "write_policy": "draft_only"}

    if _contains_any(text, FORMAT_TERMS):
        return {"intent": "format_entries", "target": "current_sheet", "field": "unknown", "write_policy": "draft_only"}

    return {"intent": "legacy_chat", "target": "unknown", "field": "unknown", "write_policy": "read_only"}


def apply_accounting_command(prompt: str, payload: ChatSpreadsheetRequest) -> dict[str, Any] | None:
    action = classify_accounting_command(prompt, payload)
    intent = action.get("intent")

    if intent == "legacy_chat":
        return None

    if intent == "explain_capability":
        return {
            "message": (
                "نعم، أستطيع تنفيذ الأوامر المحاسبية على الورقة كمسودة ذكية: تغيير التاريخ، تغيير الحساب، تجهيز قيد عكسي، "
                "مراجعة التوازن، وتجهيز القيود قبل الترحيل. أي كتابة فعلية داخل Odoo تحتاج زر ترحيل أو اعتماد واضح."
            ),
            "grid_data": None,
            "intent": intent,
            "action": action,
        }

    if intent == "post_entries":
        return {
            "message": (
                "فهمت أنك تريد ترحيل القيود إلى Odoo. لا أنفذ الترحيل من التشات مباشرة. "
                "اضغط على رقم القيد داخل الورقة ثم استخدم زر «ترحيل القيد إلى Odoo» بعد مراجعة التفاصيل."
            ),
            "grid_data": None,
            "intent": intent,
            "action": action,
        }

    sheet_name, grid = _sheet_rows(payload)
    if not grid:
        return {
            "message": "لا توجد بيانات في الورقة الحالية لتنفيذ الأمر المحاسبي.",
            "grid_data": None,
            "intent": intent,
            "action": action,
        }

    grid = _ensure_rectangular(grid)
    header_idx = _find_header_row(grid)
    header = grid[header_idx]
    date_col = _find_column(header, {"التاريخ", "date"}, ["تاريخ", "date"], 1)
    account_col = _find_column(header, {"رمز الحساب", "account code", "account"}, ["حساب", "account"], 4)
    debit_col = _find_column(header, {"مدين", "debit"}, ["مدين", "debit"], 6)
    credit_col = _find_column(header, {"دائن", "credit"}, ["دائن", "credit"], 7)
    grid = _ensure_rectangular(grid, max(date_col, account_col, debit_col, credit_col) + 1)

    changed = 0

    if intent == "change_date":
        target_date = action.get("value")
        display_date = action.get("display_value") or target_date
        for row in grid[header_idx + 1:]:
            if not _row_has_data(row):
                continue
            row[date_col] = str(target_date)
            changed += 1
        return {
            "message": (
                f"تم فهم الأمر محاسبيًا: تغيير تاريخ القيود في الورقة الحالية إلى {display_date}.\n\n"
                f"جهزت مسودة التعديل داخل الجدول لعدد {changed} سطر. لم أكتب أي شيء داخل Odoo مباشرة."
            ),
            "grid_data": grid,
            "active_sheet_name": "مسودة أمر محاسبي - تعديل التاريخ",
            "intent": intent,
            "action": action,
            "changed_rows": changed,
        }

    if intent == "change_account":
        target_account = action.get("value")
        if not target_account:
            return {
                "message": "فهمت أنك تريد تغيير الحساب، لكن لم أجد رقم الحساب الجديد في الأمر. اكتب مثلًا: غيّر الحساب إلى 104041.",
                "grid_data": None,
                "intent": intent,
                "action": action,
            }
        for row in grid[header_idx + 1:]:
            if not _row_has_data(row):
                continue
            row[account_col] = str(target_account)
            changed += 1
        return {
            "message": f"جهزت مسودة تغيير رمز الحساب إلى {target_account} لعدد {changed} سطر. لم أكتب أي شيء في Odoo مباشرة.",
            "grid_data": grid,
            "active_sheet_name": "مسودة أمر محاسبي - تعديل الحساب",
            "intent": intent,
            "action": action,
            "changed_rows": changed,
        }

    if intent == "reverse_entries":
        for row in grid[header_idx + 1:]:
            if not _row_has_data(row):
                continue
            debit = row[debit_col]
            credit = row[credit_col]
            row[debit_col], row[credit_col] = credit, debit
            changed += 1
        return {
            "message": f"جهزت قيدًا عكسيًا كمسودة داخل الجدول لعدد {changed} سطر. راجع القيد قبل أي ترحيل إلى Odoo.",
            "grid_data": grid,
            "active_sheet_name": "مسودة قيد عكسي",
            "intent": intent,
            "action": action,
            "changed_rows": changed,
        }

    if intent in {"balance_entries", "format_entries"}:
        debit_total = 0.0
        credit_total = 0.0
        for row in grid[header_idx + 1:]:
            try:
                debit_total += float(str(row[debit_col] or "0").replace(",", ""))
                credit_total += float(str(row[credit_col] or "0").replace(",", ""))
            except Exception:
                continue
        diff = round(debit_total - credit_total, 2)
        status = "متوازن" if abs(diff) <= 0.01 else f"غير متوازن، الفرق {diff}"
        return {
            "message": f"راجعت الورقة محاسبيًا: إجمالي المدين {debit_total:,.2f}، إجمالي الدائن {credit_total:,.2f}. الحالة: {status}.",
            "grid_data": grid,
            "intent": intent,
            "action": action,
            "debit_total": debit_total,
            "credit_total": credit_total,
            "difference": diff,
        }

    return None


def parse_lenient_json(content: str) -> dict[str, Any] | None:
    """Parse imperfect LLM JSON without throwing user-visible JSON errors."""
    if not content:
        return None

    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    candidates = [cleaned]
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(cleaned[first:last + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    return {
        "message": cleaned[:1200] if cleaned else "لم أستطع تحويل رد النموذج إلى JSON صالح، لكن لم يتم تنفيذ أي تعديل.",
        "grid_data": None,
        "intent": "llm_text_fallback",
    }
