from __future__ import annotations

import inspect

import pytest

from app.ml.name_matching.features import FEATURE_NAMES, extract_pair_features
from app.ml.name_matching.runtime import (
    LocalNameMatcher,
    explain_similarity,
    get_local_name_matcher,
    hybrid_similarity,
)


@pytest.mark.parametrize(
    ("query", "candidate"),
    [
        ("غلام", "غلام"),
        ("غلام", "Ghulam"),
        ("غلام", "Gulam Trading Est."),
        ("غلام", "Gholam"),
        ("غلام", "دفعة إلى غلام محمد"),
        ("محمد", "Mohammed Ahmed"),
        ("عبدالله", "Abdullah Contracting"),
        ("يوسف", "Youssef Trading"),
        ("عبداللطيف", "Abdul Latif Trading"),
        ("غيث", "Ghaith Trading"),
    ],
)
def test_valid_arabic_english_variants_are_matches(
    query: str,
    candidate: str,
) -> None:
    result = explain_similarity(query, candidate)

    assert result.score >= 0.80
    assert result.decision == "match"


@pytest.mark.parametrize(
    ("query", "candidate"),
    [
        (
            "غلام",
            "شركة هلا السعودية للخدمات البترولية: 31978",
        ),
        ("غلام", "هلا"),
        ("غلام", "Hala"),
        ("غلام", "Ghada"),
        ("غلام", "Other Receivable"),
        ("غلام", "31978"),
        ("محمد", "محمود"),
        ("احمد", "حمد"),
        ("عبدالله", "عبيد الله"),
        ("طلال", "Tala Trading"),
        ("رشا", "Rashad"),
        ("حسن", "Hussain"),
        ("حسين", "Hassan"),
    ],
)
def test_hard_negative_names_are_not_matches(
    query: str,
    candidate: str,
) -> None:
    result = explain_similarity(query, candidate)

    assert result.score < 0.80
    assert result.decision != "match"


def test_reported_false_positive_is_rejected() -> None:
    score = hybrid_similarity(
        "غلام",
        "شركة هلا السعودية للخدمات البترولية: 31978",
    )

    assert score < 0.20


def test_feature_and_artifact_schemas_are_aligned() -> None:
    matcher = get_local_name_matcher()
    values = extract_pair_features("غلام", "Ghulam Trading Est.")

    assert matcher.feature_names == FEATURE_NAMES
    assert len(values) == len(FEATURE_NAMES)
    assert len(matcher.coefficients) == len(FEATURE_NAMES)


def test_runtime_does_not_import_scikit_learn() -> None:
    import app.ml.name_matching.features as features_module
    import app.ml.name_matching.runtime as runtime_module

    runtime_source = inspect.getsource(runtime_module)
    features_source = inspect.getsource(features_module)

    assert "from sklearn" not in runtime_source
    assert "import sklearn" not in runtime_source
    assert "from sklearn" not in features_source
    assert "import sklearn" not in features_source


def test_empty_values_are_safely_rejected() -> None:
    matcher: LocalNameMatcher = get_local_name_matcher()

    assert matcher.evaluate("", "Ghulam").score == 0.0
    assert matcher.evaluate("غلام", "").score == 0.0
