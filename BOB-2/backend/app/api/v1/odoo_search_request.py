"""Parse read-only Odoo search commands without invoking an LLM."""

from __future__ import annotations

import re

from app.ml.name_matching.normalization import normalize_text

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

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

GLOBAL_SCOPE_TERMS = (
    "جميع الحسابات",
    "كل الحسابات",
    "كافة الحسابات",
    "كامل الحسابات",
    "في الحسابات كلها",
    "كل القيود",
    "جميع القيود",
    "كافة القيود",
    "all accounts",
    "across all accounts",
    "every account",
    "all journal entries",
    "all entries",
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
    "بالعربي",
    "بالانجليزية",
    "بالإنجليزية",
    "بالانجليزي",
    "بالإنجليزي",
    "العربية",
    "الانجليزية",
    "الإنجليزية",
    "او",
    "أو",
    "ام",
    "أم",
    "و",
    "and",
    "or",
    "all",
    "related",
    "anything",
    "everything",
    "similar",
    "spellings",
    "approximately",
}


def _contains_fetch_intent(prompt: str) -> bool:
    normalized_prompt = normalize_text(prompt)
    return any(normalize_text(term) in normalized_prompt for term in FETCH_TERMS)


def _extract_search_term(prompt: str) -> str | None:
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
        normalized_token = normalize_text(token)
        if normalized_token in STOP_WORDS:
            break
        if normalized_token in {"اسم", "name", "هو", "هي"}:
            continue
        selected_tokens.append(token)
        if len(selected_tokens) >= 4:
            break

    search_term = " ".join(selected_tokens).strip()
    if len(normalize_text(search_term)) < 2:
        return None
    return search_term


def extract_account_search_request(prompt: str) -> tuple[str, str] | None:
    """Extract an exact account code and the multilingual search term."""
    if not _contains_fetch_intent(prompt):
        return None

    account_match = ACCOUNT_PATTERN.search(prompt.translate(ARABIC_DIGITS))
    if not account_match:
        return None

    account_code = re.sub(r"[^0-9.\-]", "", account_match.group(1)).strip(".-")
    if len(re.sub(r"\D", "", account_code)) < 4:
        return None

    search_term = _extract_search_term(prompt)
    if not search_term:
        return None
    return account_code, search_term


def extract_global_search_request(prompt: str) -> str | None:
    """Extract a term only from an explicit all-accounts/all-entries request."""
    normalized_prompt = normalize_text(prompt)
    if not _contains_fetch_intent(prompt):
        return None
    if not any(normalize_text(term) in normalized_prompt for term in GLOBAL_SCOPE_TERMS):
        return None

    translated_prompt = prompt.translate(ARABIC_DIGITS)
    if re.search(
        r"(?:الحساب|حساب|account)\s*[:#=\-–—]?\s*[0-9][0-9.\-]{3,20}",
        translated_prompt,
        re.IGNORECASE,
    ):
        return None

    return _extract_search_term(prompt)
