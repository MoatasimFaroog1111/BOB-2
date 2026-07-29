"""Feature extraction shared by offline training and production inference."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Callable

from app.ml.name_matching.normalization import (
    contains_arabic,
    normalize_text,
    relaxed_phonetic_skeleton,
    strict_phonetic_skeleton,
    text_spans,
    transliterate_arabic,
)

FEATURE_NAMES = [
    "native_full_ratio",
    "latin_full_ratio",
    "strict_full_ratio",
    "relaxed_full_ratio",
    "native_length_ratio",
    "latin_length_ratio",
    "strict_length_ratio",
    "relaxed_length_ratio",
    "native_exact",
    "latin_exact",
    "strict_exact",
    "relaxed_exact",
    "query_in_candidate",
    "candidate_in_query",
    "native_best_span_ratio",
    "latin_best_span_ratio",
    "strict_best_span_ratio",
    "relaxed_best_span_ratio",
    "native_exact_span",
    "latin_exact_span",
    "strict_exact_span",
    "relaxed_exact_span",
    "native_best_span_length_ratio",
    "latin_best_span_length_ratio",
    "strict_best_span_length_ratio",
    "relaxed_best_span_length_ratio",
    "native_bigram_jaccard",
    "latin_bigram_jaccard",
    "strict_bigram_jaccard",
    "relaxed_bigram_jaccard",
    "native_trigram_jaccard",
    "latin_trigram_jaccard",
    "latin_prefix_ratio",
    "strict_prefix_ratio",
    "first_strict_char_match",
    "query_token_count",
    "candidate_token_count",
    "candidate_is_numeric",
    "query_has_arabic",
    "candidate_has_arabic",
    "both_have_arabic",
]


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _length_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return min(len(left), len(right)) / max(len(left), len(right))


def _ngrams(value: str, size: int) -> set[str]:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return set()
    if len(compact) < size:
        return {compact}
    return {
        compact[index : index + size]
        for index in range(0, len(compact) - size + 1)
    }


def _jaccard(left: str, right: str, size: int) -> float:
    left_ngrams = _ngrams(left, size)
    right_ngrams = _ngrams(right, size)

    if not left_ngrams or not right_ngrams:
        return 0.0

    return len(left_ngrams & right_ngrams) / len(left_ngrams | right_ngrams)


def _common_prefix_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0

    common = 0
    for left_character, right_character in zip(left, right):
        if left_character != right_character:
            break
        common += 1

    return common / max(len(left), len(right))


def _best_span_metrics(
    query: Any,
    candidate: Any,
    transform: Callable[[Any], str],
) -> tuple[float, float, float]:
    query_form = transform(query)
    best_ratio = 0.0
    best_length_ratio = 0.0
    exact = 0.0

    for span in text_spans(candidate):
        span_form = transform(span)
        if not span_form:
            continue

        similarity = _ratio(query_form, span_form)
        span_length_ratio = _length_ratio(query_form, span_form)

        if similarity > best_ratio or (
            similarity == best_ratio and span_length_ratio > best_length_ratio
        ):
            best_ratio = similarity
            best_length_ratio = span_length_ratio

        if query_form and query_form == span_form:
            exact = 1.0

    return best_ratio, exact, best_length_ratio


def extract_pair_features(query: Any, candidate: Any) -> list[float]:
    """Produce a fixed-length, bounded numeric feature vector."""
    query_native = normalize_text(query)
    candidate_native = normalize_text(candidate)
    query_latin = transliterate_arabic(query)
    candidate_latin = transliterate_arabic(candidate)
    query_strict = strict_phonetic_skeleton(query)
    candidate_strict = strict_phonetic_skeleton(candidate)
    query_relaxed = relaxed_phonetic_skeleton(query)
    candidate_relaxed = relaxed_phonetic_skeleton(candidate)

    native_best, native_exact_span, native_span_length = _best_span_metrics(
        query,
        candidate,
        normalize_text,
    )
    latin_best, latin_exact_span, latin_span_length = _best_span_metrics(
        query,
        candidate,
        transliterate_arabic,
    )
    strict_best, strict_exact_span, strict_span_length = _best_span_metrics(
        query,
        candidate,
        strict_phonetic_skeleton,
    )
    relaxed_best, relaxed_exact_span, relaxed_span_length = _best_span_metrics(
        query,
        candidate,
        relaxed_phonetic_skeleton,
    )

    query_compact = query_native.replace(" ", "")
    candidate_compact = candidate_native.replace(" ", "")
    query_in_candidate = float(
        len(query_compact) >= 4 and query_compact in candidate_compact
    )
    candidate_in_query = float(
        len(candidate_compact) >= 4
        and candidate_compact in query_compact
        and _length_ratio(query_compact, candidate_compact) >= 0.8
    )

    query_has_arabic = contains_arabic(query)
    candidate_has_arabic = contains_arabic(candidate)

    values = [
        _ratio(query_native, candidate_native),
        _ratio(query_latin, candidate_latin),
        _ratio(query_strict, candidate_strict),
        _ratio(query_relaxed, candidate_relaxed),
        _length_ratio(query_native, candidate_native),
        _length_ratio(query_latin, candidate_latin),
        _length_ratio(query_strict, candidate_strict),
        _length_ratio(query_relaxed, candidate_relaxed),
        float(bool(query_native) and query_native == candidate_native),
        float(bool(query_latin) and query_latin == candidate_latin),
        float(len(query_strict) >= 2 and query_strict == candidate_strict),
        float(len(query_relaxed) >= 2 and query_relaxed == candidate_relaxed),
        query_in_candidate,
        candidate_in_query,
        native_best,
        latin_best,
        strict_best,
        relaxed_best,
        native_exact_span,
        latin_exact_span,
        strict_exact_span,
        relaxed_exact_span,
        native_span_length,
        latin_span_length,
        strict_span_length,
        relaxed_span_length,
        _jaccard(query_native, candidate_native, 2),
        _jaccard(query_latin, candidate_latin, 2),
        _jaccard(query_strict, candidate_strict, 2),
        _jaccard(query_relaxed, candidate_relaxed, 2),
        _jaccard(query_native, candidate_native, 3),
        _jaccard(query_latin, candidate_latin, 3),
        _common_prefix_ratio(query_latin, candidate_latin),
        _common_prefix_ratio(query_strict, candidate_strict),
        float(
            bool(query_strict)
            and bool(candidate_strict)
            and query_strict[0] == candidate_strict[0]
        ),
        min(len(query_native.split()), 10) / 10.0,
        min(len(candidate_native.split()), 20) / 20.0,
        float(
            bool(candidate_native)
            and candidate_native.replace(" ", "").isdigit()
        ),
        float(query_has_arabic),
        float(candidate_has_arabic),
        float(query_has_arabic and candidate_has_arabic),
    ]

    if len(values) != len(FEATURE_NAMES):
        raise RuntimeError("Name matcher feature schema is inconsistent.")

    return values


def feature_mapping(query: Any, candidate: Any) -> dict[str, float]:
    return dict(zip(FEATURE_NAMES, extract_pair_features(query, candidate), strict=True))
