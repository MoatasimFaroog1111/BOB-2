"""Provider-independent partner-name matching domain service."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_ARABIC_TO_LATIN = {
    "ا": "a", "أ": "a", "إ": "i", "آ": "a", "ء": "a", "ؤ": "o", "ئ": "e",
    "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "th", "ر": "r", "ز": "z", "س": "s", "ش": "sh",
    "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh",
    "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n",
    "ه": "h", "ة": "a", "و": "w", "ي": "y", "ى": "a",
}


def normalize_partner_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    normalized = normalized.lower()
    normalized = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]", "", normalized)
    normalized = normalized.replace("ـ", "").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    normalized = normalized.replace("ى", "ي").replace("ة", "ه")
    normalized = re.sub(r"[^\w\u0600-\u06FF\s]", " ", normalized)
    normalized = re.sub(r"\b(company|co|corp|corporation|inc|ltd|llc|est)\b", " ", normalized)
    normalized = re.sub(r"(شركة|شركه|مؤسسه|مؤسسة|مكتب|مقاولات|التجارية|العامه|العامة)", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _transliterate(value: str) -> str:
    return re.sub(r"\s+", " ", "".join(_ARABIC_TO_LATIN.get(ch, ch) for ch in value or "")).strip()


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {token for token in left.split() if token}
    right_tokens = {token for token in right.split() if token}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def partner_name_similarity(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    native = text_similarity(query, candidate) * 0.75 + _token_overlap(query, candidate) * 0.25
    query_latin, candidate_latin = _transliterate(query), _transliterate(candidate)
    cross_lingual = text_similarity(query_latin, candidate_latin) * 0.75 + _token_overlap(query_latin, candidate_latin) * 0.25
    boost = 0.15 if query in candidate or candidate in query else 0.0
    return min(1.0, max(native, cross_lingual) + boost)


def closest_partner(partners: list[dict], partner_name: str) -> tuple[int | None, str, float]:
    query = normalize_partner_name(partner_name)
    if not query:
        return None, "", 0.0
    best: dict | None = None
    best_score = 0.0
    for partner in partners or []:
        candidate = normalize_partner_name(partner.get("name") or "")
        score = partner_name_similarity(query, candidate) if candidate else 0.0
        if score > best_score:
            best, best_score = partner, score
    if best is not None and best_score >= 0.5:
        return best.get("id"), best.get("name") or "", best_score
    return None, "", 0.0
