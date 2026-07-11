import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.api.v1.chat_journal_lookup import chat_spreadsheet_with_odoo_entry_lookup
from app.api.v1.erp import ChatSpreadsheetRequest
from app.services.llm_service import chat as llm_chat

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

DATE_DMY_PATTERN = re.compile(r"\b([0-3]?\d)[/-]([01]?\d)[/-]((?:19|20)\d{2})\b")
DATE_ISO_PATTERN = re.compile(r"\b((?:19|20)\d{2})-([01]?\d)-([0-3]?\d)\b")
ENTRY_REF_PATTERN = re.compile(
    r"\b([A-Z][A-Z0-9]{1,12}\s*/\s*[0-9]{4}\s*(?:/\s*[0-9]{1,2})?\s*/\s*[0-9]{3,8})\b",
    re.IGNORECASE,
)
NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")

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
    "اقرأ",
    "إقرأ",
    "تفاصيل",
    "استخرج",
    "fetch",
    "get",
    "show",
    "display",
    "open",
    "read",
    "lookup",
    "details",
]

WRITE_TERMS = [
    "غير",
    "غيّر",
    "تغيير",
    "عدل",
    "تعديل",
    "بدل",
    "استبدل",
    "اجعل",
    "خلي",
    "صحح",
    "تصحيح",
    "update",
    "change",
    "edit",
    "modify",
    "set",
    "make",
    "fix",
]

POST_TERMS = ["رحل", "ترحيل", "اعتمد", "اعتماد", "سجل في اودو", "تسجيل في اودو", "post", "approve", "submit"]
REVERSE_TERMS = ["اعكس", "عكس", "قيد عكسي", "reverse"]
BALANCE_TERMS = ["وازن", "التوازن", "متوازن", "الفرق", "balance", "balanced"]
CAPABILITY_TERMS = ["هل", "تستطيع", "يمكنك", "ممكن", "تقدر", "can", "could", "able"]
DATE_TERMS = ["تاريخ", "التاريخ", "تايخ", "date"]
ACCOUNT_TERMS = ["حساب", "الحساب", "رمز الحساب", "كود الحساب", "account"]
PARTNER_TERMS = ["شريك", "الشريك", "عميل", "مورد", "partner", "customer", "vendor", "supplier"]
LABEL_TERMS = ["بيان", "البيان", "وصف", "الوصف", "description", "label", "memo"]

ACTION_SCHEMA: dict[str, Any] = {
    "intent": [
        "fetch_entries",
        "change_date",
        "change_account",
        "change_partner",
        "change_label",
        "reverse_entries",
        "post_entries",
        "balance_entries",
        "explain_capability",
        "legacy_chat",
        "clarify",
    ],
    "target": ["current_sheet", "prompt_entries", "selected_entries", "unknown"],
    "field": ["date", "account", "partner", "label", "amount", "unknown"],
    "write_policy": ["read_only", "draft_only", "requires_confirmation"],
}


def _normal(value: str) -> str:
    return (value or "").translate(ARABIC_DIGITS).strip().lower()


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term.lower() in text for term in terms)


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


def _entry_refs(prompt: str) -> list[str]:
    refs: list[str] = []
    for match in ENTRY_REF_PATTERN.finditer((prompt or "").translate(ARABIC_DIGITS)):
        value = re.sub(r"\s*/\s*", "/", match.group(1).upper()).strip()
        if value not in refs:
            refs.append(value)
    return refs


def _last_number(prompt: str) -> Optional[str]:
    matches = NUMBER_PATTERN.findall(_normal(prompt))
    return matches[-1].replace(",", "") if matches else None


def _last_value_after_terms(prompt: str, terms: list[str]) -> Optional[str]:
    text = prompt or ""
    lowered = _normal(prompt)
    for term in terms:
        idx = lowered.rfind(term.lower())
        if idx != -1:
            raw = text[idx + len(term):].strip(" :：-–—=\t\n")
            if raw:
                return raw.split("\n", 1)[0].strip()
    return None


def _sheet_rows(payload: ChatSpreadsheetRequest) -> tuple[str, list[list[str]]]:
    for sheet in payload.sheets or []:
        if sheet.id == payload.active_sheet_id:
            return sheet.name or "", [list(row) for row in sheet.gridData or []]
    if payload.sheets:
        first = payload.sheets[0]
        return first.name or "", [list(row) for row in first.gridData or []]
    return "", []


def _sheet_summary(payload: ChatSpreadsheetRequest) -> dict[str, Any]:
    sheet_name, grid = _sheet_rows(payload)
    visible_rows = [row for row in grid if any(str(cell or "").strip() for cell in row)]
    return {
        "sheet_name": sheet_name,
        "row_count": len(grid),
        "non_empty_rows": len(visible_rows),
        "sample_rows": visible_rows[:8],
        "contains_entry_refs": bool(_entry_refs("\n".join(" ".join(str(cell or "") for cell in row) for row in visible_rows[:200]))),
    }


def _find_header_row(grid: list[list[str]]) -> int:
    for index, row in enumerate(grid[:15]):
        labels = [str(cell or "").strip().lower() for cell in row]
        has_entry = any(label in {"رقم القيد", "entry number", "journal entry", "move"} for label in labels)
        has_date = any(label in {"التاريخ", "date"} for label in labels)
        has_debit = any(label in {"مدين", "debit"} for label in labels)
        has_credit = any(label in {"دائن", "credit"} for label in labels)
        has_account = any(label in {"رمز الحساب", "account code", "account"} or "حساب" in label for label in labels)
        if (has_entry and has_date) or (has_debit and has_credit) or (has_account and has_date):
            return index
    return 0


def _find_column(header: list[str], exact: set[str], contains: list[str], fallback: int) -> int:
    for index, value in enumerate(header):
        label = str(value or "").strip().lower()
        if label in exact or any(term in label for term in contains):
            return index
    return fallback


def _ensure_rectangular(grid: list[list[str]], min_width: int | None = None) -> list[list[str]]:
    width = max([len(row) for row in grid] + [min_width or 0, 1])
    return [list(row) + [""] * (width - len(row)) for row in grid]


def _row_has_data(row: list[str]) -> bool:
    return any(str(cell or "").strip() for cell in row)


def _parse_llm_json(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    candidates = [text]
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first:last + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return None


def _deterministic_intent(prompt: str, payload: ChatSpreadsheetRequest) -> dict[str, Any]:
    text = _normal(prompt)
    refs = _entry_refs(prompt)
    date_value = _parse_date(prompt)
    sheet = _sheet_summary(payload)

    # Fetch commands must win over words inside pasted Odoo descriptions such as "Reversal of".
    if _contains_any(text, FETCH_TERMS):
        return {
            "intent": "fetch_entries",
            "target": "prompt_entries" if refs else "current_sheet",
            "field": "unknown",
            "value": None,
            "entry_refs": refs,
            "confidence": 0.99,
            "write_policy": "read_only",
            "reason": "explicit fetch/read command",
        }

    if _contains_any(text, CAPABILITY_TERMS) and (_contains_any(text, WRITE_TERMS) or _contains_any(text, POST_TERMS)):
        return {"intent": "explain_capability", "target": "current_sheet", "field": "unknown", "value": None, "entry_refs": refs, "confidence": 0.95, "write_policy": "read_only", "reason": "capability question"}

    if _contains_any(text, POST_TERMS):
        return {"intent": "post_entries", "target": "prompt_entries" if refs else "current_sheet", "field": "unknown", "value": None, "entry_refs": refs, "confidence": 0.95, "write_policy": "requires_confirmation", "reason": "posting command"}

    if _contains_any(text, REVERSE_TERMS):
        return {"intent": "reverse_entries", "target": "current_sheet", "field": "unknown", "value": None, "entry_refs": refs, "confidence": 0.90, "write_policy": "draft_only", "reason": "explicit reversal command"}

    if date_value and (_contains_any(text, WRITE_TERMS) or _contains_any(text, DATE_TERMS)):
        return {"intent": "change_date", "target": "current_sheet", "field": "date", "value": date_value[0], "display_value": date_value[1], "entry_refs": refs, "confidence": 0.98, "write_policy": "draft_only", "reason": "date change command"}

    if _contains_any(text, ACCOUNT_TERMS) and _contains_any(text, WRITE_TERMS):
        return {"intent": "change_account", "target": "current_sheet", "field": "account", "value": _last_number(prompt), "entry_refs": refs, "confidence": 0.92, "write_policy": "draft_only", "reason": "account change command"}

    if _contains_any(text, PARTNER_TERMS) and _contains_any(text, WRITE_TERMS):
        return {"intent": "change_partner", "target": "current_sheet", "field": "partner", "value": _last_value_after_terms(prompt, PARTNER_TERMS), "entry_refs": refs, "confidence": 0.85, "write_policy": "draft_only", "reason": "partner change command"}

    if _contains_any(text, LABEL_TERMS) and _contains_any(text, WRITE_TERMS):
        return {"intent": "change_label", "target": "current_sheet", "field": "label", "value": _last_value_after_terms(prompt, LABEL_TERMS), "entry_refs": refs, "confidence": 0.85, "write_policy": "draft_only", "reason": "label change command"}

    if _contains_any(text, BALANCE_TERMS):
        return {"intent": "balance_entries", "target": "current_sheet", "field": "amount", "value": None, "entry_refs": refs, "confidence": 0.9, "write_policy": "read_only", "reason": "balance review command"}

    if refs and not _contains_any(text, WRITE_TERMS) and not _contains_any(text, POST_TERMS):
        return {"intent": "fetch_entries", "target": "prompt_entries", "field": "unknown", "value": None, "entry_refs": refs, "confidence": 0.80, "write_policy": "read_only", "reason": "pasted entry references"}

    return {"intent": "legacy_chat", "target": "unknown", "field": "unknown", "value": None, "entry_refs": refs, "confidence": 0.2, "write_policy": "read_only", "reason": "no accounting action detected", "sheet": sheet}


def interpret_natural_language(prompt: str, payload: ChatSpreadsheetRequest) -> dict[str, Any]:
    deterministic = _deterministic_intent(prompt, payload)

    # Hard safety overrides: these are deterministic and should not be overturned by an LLM.
    if deterministic.get("confidence", 0) >= 0.95 or deterministic.get("intent") in {"fetch_entries", "post_entries"}:
        return deterministic | {"model_source": "deterministic_override"}

    system_prompt = """
You are GuardianAI's Natural Language Command Model for accounting operations.
Return ONLY valid JSON. No markdown. No explanations outside JSON.

Classify the user's natural language command into this schema:
{
  "intent": "fetch_entries | change_date | change_account | change_partner | change_label | reverse_entries | post_entries | balance_entries | explain_capability | legacy_chat | clarify",
  "target": "current_sheet | prompt_entries | selected_entries | unknown",
  "field": "date | account | partner | label | amount | unknown",
  "value": string|null,
  "display_value": string|null,
  "entry_refs": string[],
  "confidence": number,
  "write_policy": "read_only | draft_only | requires_confirmation",
  "reason": string
}

Critical rules:
- If the user says احضر/أحضر/اجلب/هات/fetch/show/get/read/open/details entries from Odoo, intent MUST be fetch_entries even if pasted entry descriptions include words like Reversal, reverse, adjustment, cut-off.
- If the user asks to post/approve/write to Odoo, intent MUST be post_entries and write_policy MUST be requires_confirmation.
- If the user changes date/account/partner/label, write_policy MUST be draft_only.
- Never invent account codes or partners.
""".strip()

    user_prompt = json.dumps(
        {
            "user_command": prompt,
            "deterministic_guess": deterministic,
            "sheet_summary": _sheet_summary(payload),
            "action_schema": ACTION_SCHEMA,
        },
        ensure_ascii=False,
    )

    raw = llm_chat(system_prompt, user_prompt, temperature=0.0, timeout=45)
    parsed = _parse_llm_json(raw)
    if not parsed:
        return deterministic | {"model_source": "deterministic_fallback"}

    intent = parsed.get("intent") or "legacy_chat"
    if intent not in ACTION_SCHEMA["intent"]:
        return deterministic | {"model_source": "invalid_llm_fallback"}

    # Preserve deterministic fetch priority over misleading words in pasted data.
    if deterministic.get("intent") == "fetch_entries":
        return deterministic | {"model_source": "fetch_priority_override", "llm_guess": parsed}

    return {
        "intent": intent,
        "target": parsed.get("target") if parsed.get("target") in ACTION_SCHEMA["target"] else deterministic.get("target", "unknown"),
        "field": parsed.get("field") if parsed.get("field") in ACTION_SCHEMA["field"] else deterministic.get("field", "unknown"),
        "value": parsed.get("value", deterministic.get("value")),
        "display_value": parsed.get("display_value", deterministic.get("display_value")),
        "entry_refs": parsed.get("entry_refs") if isinstance(parsed.get("entry_refs"), list) else deterministic.get("entry_refs", []),
        "confidence": float(parsed.get("confidence") or deterministic.get("confidence") or 0.5),
        "write_policy": parsed.get("write_policy") if parsed.get("write_policy") in ACTION_SCHEMA["write_policy"] else deterministic.get("write_policy", "read_only"),
        "reason": parsed.get("reason") or deterministic.get("reason") or "classified by natural language model",
        "model_source": "llm_structured_nlu",
    }


def _prepare_grid(payload: ChatSpreadsheetRequest) -> tuple[str, list[list[str]], int, dict[str, int]]:
    sheet_name, grid = _sheet_rows(payload)
    grid = _ensure_rectangular(grid)
    header_idx = _find_header_row(grid)
    header = grid[header_idx] if grid else []
    columns = {
        "entry": _find_column(header, {"رقم القيد", "entry number", "journal entry", "move"}, ["قيد", "entry", "move"], 0),
        "date": _find_column(header, {"التاريخ", "date"}, ["تاريخ", "date"], 1),
        "journal": _find_column(header, {"الدفتر", "journal"}, ["دفتر", "journal"], 2),
        "partner": _find_column(header, {"الشريك", "partner"}, ["شريك", "partner", "customer", "vendor"], 3),
        "account": _find_column(header, {"رمز الحساب", "account code", "account"}, ["حساب", "account"], 4),
        "label": _find_column(header, {"البيان", "description", "label", "memo"}, ["بيان", "وصف", "description", "label", "memo"], 6),
        "debit": _find_column(header, {"مدين", "debit"}, ["مدين", "debit"], 7),
        "credit": _find_column(header, {"دائن", "credit"}, ["دائن", "credit"], 8),
    }
    grid = _ensure_rectangular(grid, max(columns.values()) + 1)
    return sheet_name, grid, header_idx, columns


def _target_row(action: dict[str, Any], row: list[str], columns: dict[str, int]) -> bool:
    refs = [str(ref).upper() for ref in action.get("entry_refs") or []]
    if not refs:
        return _row_has_data(row)
    row_text = " ".join(str(cell or "").upper() for cell in row)
    return any(ref in row_text for ref in refs)


def execute_natural_language_command(
    prompt: str,
    payload: ChatSpreadsheetRequest,
    db_session: Optional[Session] = None,
) -> dict[str, Any] | None:
    action = interpret_natural_language(prompt, payload)
    intent = action.get("intent")

    if intent == "legacy_chat":
        return None

    if intent == "fetch_entries":
        if db_session is None:
            return {
                "message": "فهمت أن هذا أمر جلب قيود من Odoo، لكن جلسة قاعدة البيانات غير متاحة.",
                "grid_data": None,
                "intent": intent,
                "action": action,
            }
        return chat_spreadsheet_with_odoo_entry_lookup(payload=payload, db_session=db_session) | {"intent": intent, "action": action}

    if intent == "explain_capability":
        return {
            "message": (
                "تم دمج نموذج لغة طبيعية كامل مع النظام: أفهم أوامر مثل جلب القيود من Odoo، تغيير التاريخ، تغيير الحساب، "
                "تغيير الشريك أو البيان، عكس القيود، مراجعة التوازن، وطلبات الترحيل. التعديلات تكون مسودات داخل الجدول، "
                "وأي كتابة فعلية في Odoo تحتاج زر ترحيل أو اعتماد واضح."
            ),
            "grid_data": None,
            "intent": intent,
            "action": action,
        }

    if intent == "post_entries":
        return {
            "message": (
                "فهمت أمر الترحيل. لن أرحّل مباشرة من التشات. اضغط على رقم القيد داخل الورقة، راجع تفاصيله، "
                "ثم استخدم زر «ترحيل القيد إلى Odoo»."
            ),
            "grid_data": None,
            "intent": intent,
            "action": action,
        }

    sheet_name, grid, header_idx, columns = _prepare_grid(payload)
    if not grid:
        return {"message": "فهمت الأمر، لكن لا توجد بيانات في الورقة الحالية.", "grid_data": None, "intent": intent, "action": action}

    changed = 0

    if intent == "change_date":
        value = action.get("value") or (_parse_date(prompt) or (None, None))[0]
        display = action.get("display_value") or value
        if not value:
            return {"message": "فهمت أنك تريد تغيير التاريخ، لكن لم أجد التاريخ الجديد في الأمر.", "grid_data": None, "intent": intent, "action": action}
        for row in grid[header_idx + 1:]:
            if _target_row(action, row, columns):
                row[columns["date"]] = str(value)
                changed += 1
        return {
            "message": f"فهمت الأمر كنموذج لغة طبيعية: تغيير التاريخ إلى {display}. جهزت مسودة تعديل لعدد {changed} سطر، ولم أكتب أي شيء في Odoo مباشرة.",
            "grid_data": grid,
            "active_sheet_name": "مسودة NLU - تعديل التاريخ",
            "intent": intent,
            "action": action,
            "changed_rows": changed,
        }

    if intent == "change_account":
        value = action.get("value") or _last_number(prompt)
        if not value:
            return {"message": "فهمت أنك تريد تغيير الحساب، لكن لم أجد رقم الحساب الجديد.", "grid_data": None, "intent": intent, "action": action}
        for row in grid[header_idx + 1:]:
            if _target_row(action, row, columns):
                row[columns["account"]] = str(value)
                changed += 1
        return {"message": f"جهزت مسودة تغيير الحساب إلى {value} لعدد {changed} سطر.", "grid_data": grid, "active_sheet_name": "مسودة NLU - تعديل الحساب", "intent": intent, "action": action, "changed_rows": changed}

    if intent == "change_partner":
        value = action.get("value") or _last_value_after_terms(prompt, PARTNER_TERMS)
        if not value:
            return {"message": "فهمت أنك تريد تغيير الشريك، لكن لم أجد اسم الشريك الجديد.", "grid_data": None, "intent": intent, "action": action}
        for row in grid[header_idx + 1:]:
            if _target_row(action, row, columns):
                row[columns["partner"]] = str(value)
                changed += 1
        return {"message": f"جهزت مسودة تغيير الشريك إلى {value} لعدد {changed} سطر.", "grid_data": grid, "active_sheet_name": "مسودة NLU - تعديل الشريك", "intent": intent, "action": action, "changed_rows": changed}

    if intent == "change_label":
        value = action.get("value") or _last_value_after_terms(prompt, LABEL_TERMS)
        if not value:
            return {"message": "فهمت أنك تريد تغيير البيان، لكن لم أجد البيان الجديد.", "grid_data": None, "intent": intent, "action": action}
        for row in grid[header_idx + 1:]:
            if _target_row(action, row, columns):
                row[columns["label"]] = str(value)
                changed += 1
        return {"message": f"جهزت مسودة تغيير البيان إلى: {value} لعدد {changed} سطر.", "grid_data": grid, "active_sheet_name": "مسودة NLU - تعديل البيان", "intent": intent, "action": action, "changed_rows": changed}

    if intent == "reverse_entries":
        for row in grid[header_idx + 1:]:
            if _target_row(action, row, columns):
                row[columns["debit"]], row[columns["credit"]] = row[columns["credit"]], row[columns["debit"]]
                changed += 1
        return {"message": f"جهزت قيدًا عكسيًا كمسودة لعدد {changed} سطر. لم أكتب أي شيء داخل Odoo.", "grid_data": grid, "active_sheet_name": "مسودة NLU - قيد عكسي", "intent": intent, "action": action, "changed_rows": changed}

    if intent == "balance_entries":
        debit_total = 0.0
        credit_total = 0.0
        for row in grid[header_idx + 1:]:
            try:
                debit_total += float(str(row[columns["debit"]] or "0").replace(",", ""))
                credit_total += float(str(row[columns["credit"]] or "0").replace(",", ""))
            except Exception:
                continue
        difference = round(debit_total - credit_total, 2)
        status = "متوازن" if abs(difference) <= 0.01 else f"غير متوازن، الفرق {difference:,.2f}"
        return {
            "message": f"راجعت التوازن: إجمالي المدين {debit_total:,.2f}، إجمالي الدائن {credit_total:,.2f}. الحالة: {status}.",
            "grid_data": grid,
            "intent": intent,
            "action": action,
            "debit_total": debit_total,
            "credit_total": credit_total,
            "difference": difference,
        }

    return {"message": "فهمت أن هذا أمر محاسبي، لكن أحتاج توضيح الحقل والقيمة المطلوبة.", "grid_data": None, "intent": "clarify", "action": action}
