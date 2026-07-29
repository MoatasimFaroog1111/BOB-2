"""Text normalization utilities for the local multilingual name matcher.

This module intentionally uses only the Python standard library so production
inference does not need scikit-learn or any external AI service.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

MAX_TEXT_CHARS = 4_000
MAX_SPAN_TOKENS = 120

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


def _bounded_text(value: Any) -> str:
    return str(value or "")[:MAX_TEXT_CHARS]


def contains_arabic(value: Any) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", _bounded_text(value)))


def normalize_text(value: Any) -> str:
    """Return a stable Arabic/Latin representation suitable for comparison."""
    text = _bounded_text(value).translate(ARABIC_DIGITS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower()
    text = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]", "", text)
    text = text.replace("ـ", "")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def transliterate_arabic(value: Any) -> str:
    normalized = normalize_text(value)
    translated = "".join(ARABIC_TO_LATIN.get(character, character) for character in normalized)
    return re.sub(r"\s+", " ", translated).strip()


def _phonetic_base(value: Any) -> str:
    text = transliterate_arabic(value)
    text = (
        text.replace("ph", "f")
        .replace("kh", "x")
        .replace("gh", "g")
        .replace("sh", "s")
        .replace("th", "t")
    )
    text = (
        text.replace("ou", "u")
        .replace("oo", "u")
        .replace("ee", "i")
        .replace("aa", "a")
    )

    # Initial y is commonly consonantal (Yousef); internal y is commonly a
    # vowel marker (Ghaith/Zakaria) and is therefore removed with vowels.
    if text.startswith("y"):
        text = "Y" + text[1:].replace("y", "i")
    else:
        text = text.replace("y", "i")

    text = text.replace("w", "u")
    text = re.sub(r"[aeiou]", "", text)
    text = text.replace("Y", "y")
    return re.sub(r"[^a-z0-9]+", "", text)


def strict_phonetic_skeleton(value: Any) -> str:
    """Consonant skeleton that preserves doubled consonants."""
    return _phonetic_base(value)


def relaxed_phonetic_skeleton(value: Any) -> str:
    """Consonant skeleton tolerant of doubled consonants."""
    return re.sub(r"(.)\1+", r"\1", _phonetic_base(value))


def text_spans(value: Any, *, max_words: int = 4) -> list[str]:
    """Return contiguous token spans, bounded to protect request latency."""
    tokens = normalize_text(value).split()[:MAX_SPAN_TOKENS]
    if not tokens:
        return [""]

    spans: list[str] = []
    largest = min(max_words, len(tokens))

    for size in range(1, largest + 1):
        for start in range(0, len(tokens) - size + 1):
            spans.append(" ".join(tokens[start : start + size]))

    return spans
