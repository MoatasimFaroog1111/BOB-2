"""Dependency-free runtime for the locally trained hybrid name matcher."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping

from app.ml.name_matching.features import FEATURE_NAMES, feature_mapping
from app.ml.name_matching.normalization import (
    normalize_text,
    strict_phonetic_skeleton,
    text_spans,
    transliterate_arabic,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchScore:
    score: float
    model_score: float
    rule_score: float
    decision: str
    reason: str
    model_version: str


class LocalNameMatcher:
    """Run Logistic Regression inference from audited JSON weights."""

    def __init__(self, artifact: Mapping[str, Any]):
        feature_names = list(artifact.get("feature_names") or [])
        coefficients = [float(value) for value in artifact.get("coefficients") or []]

        if feature_names != FEATURE_NAMES:
            raise ValueError("Name matcher artifact feature schema does not match runtime.")
        if len(coefficients) != len(FEATURE_NAMES):
            raise ValueError("Name matcher artifact coefficient count is invalid.")

        self.feature_names = feature_names
        self.coefficients = coefficients
        self.intercept = float(artifact["intercept"])
        self.accept_threshold = float(artifact.get("accept_threshold", 0.80))
        self.review_threshold = float(artifact.get("review_threshold", 0.65))
        self.model_version = str(artifact.get("model_version") or "unknown")
        self.rule_thresholds = dict(artifact.get("rule_thresholds") or {})

        values = [self.intercept, *self.coefficients]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Name matcher artifact contains non-finite weights.")

    @classmethod
    def from_package(cls) -> "LocalNameMatcher":
        artifact_path = files("app.ml.name_matching").joinpath("model_weights.json")
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        return cls(artifact)

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            denominator = 1.0 + math.exp(-value)
            return 1.0 / denominator

        exponential = math.exp(value)
        return exponential / (1.0 + exponential)

    def _predict_model(self, values: Mapping[str, float]) -> float:
        linear = self.intercept

        for feature_name, coefficient in zip(
            self.feature_names,
            self.coefficients,
            strict=True,
        ):
            linear += coefficient * float(values[feature_name])

        return self._sigmoid(linear)

    def evaluate(self, query: Any, candidate: Any) -> MatchScore:
        if not normalize_text(query) or not normalize_text(candidate):
            return MatchScore(
                score=0.0,
                model_score=0.0,
                rule_score=0.0,
                decision="reject",
                reason="empty_text",
                model_version=self.model_version,
            )

        values = feature_mapping(query, candidate)
        model_score = self._predict_model(values)
        rule_score = 0.0
        reason = "logistic_regression"

        strict_model_floor = float(
            self.rule_thresholds.get("strict_model_floor", 0.30)
        )
        relaxed_model_floor = float(
            self.rule_thresholds.get("relaxed_model_floor", 0.55)
        )
        strict_score = float(self.rule_thresholds.get("strict_score", 0.96))
        relaxed_score = float(self.rule_thresholds.get("relaxed_score", 0.88))

        if (
            values["native_exact_span"]
            or values["latin_exact_span"]
            or values["query_in_candidate"]
        ):
            rule_score = 1.0
            reason = "exact_span"
        elif (
            values["strict_exact_span"]
            and values["latin_best_span_ratio"] >= 0.64
            and model_score >= strict_model_floor
        ):
            rule_score = strict_score
            reason = "strict_phonetic_span"
        elif (
            values["relaxed_exact_span"]
            and values["strict_best_span_ratio"] >= 0.75
            and values["strict_best_span_length_ratio"] >= 0.75
            and values["latin_best_span_ratio"] >= 0.50
            and model_score >= relaxed_model_floor
        ):
            rule_score = relaxed_score
            reason = "relaxed_phonetic_span"

        score = max(model_score, rule_score)

        if score >= self.accept_threshold:
            decision = "match"
        elif score >= self.review_threshold:
            decision = "review"
        else:
            decision = "reject"

        return MatchScore(
            score=min(max(score, 0.0), 1.0),
            model_score=min(max(model_score, 0.0), 1.0),
            rule_score=min(max(rule_score, 0.0), 1.0),
            decision=decision,
            reason=reason,
            model_version=self.model_version,
        )


def _safe_fallback_similarity(query: Any, candidate: Any) -> float:
    """Conservative fallback that cannot reproduce the short-substring bug."""
    query_native = normalize_text(query)
    query_latin = transliterate_arabic(query)
    query_strict = strict_phonetic_skeleton(query)

    if not query_native:
        return 0.0

    for span in text_spans(candidate):
        if query_native == normalize_text(span):
            return 1.0
        if query_latin and query_latin == transliterate_arabic(span):
            return 1.0
        if (
            len(query_strict) >= 3
            and query_strict == strict_phonetic_skeleton(span)
            and len(query_latin) >= 4
        ):
            return 0.90

    return 0.0


@lru_cache(maxsize=1)
def get_local_name_matcher() -> LocalNameMatcher:
    return LocalNameMatcher.from_package()


def explain_similarity(query: Any, candidate: Any) -> MatchScore:
    try:
        return get_local_name_matcher().evaluate(query, candidate)
    except Exception:
        logger.exception("Local name matcher failed; using conservative fallback.")
        fallback = _safe_fallback_similarity(query, candidate)
        decision = "match" if fallback >= 0.80 else "reject"
        return MatchScore(
            score=fallback,
            model_score=0.0,
            rule_score=fallback,
            decision=decision,
            reason="safe_fallback",
            model_version="fallback",
        )


def hybrid_similarity(query: Any, candidate: Any) -> float:
    return explain_similarity(query, candidate).score
