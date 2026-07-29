from __future__ import annotations

import pytest

from app.ml.name_matching.odoo_feedback_features import load_feedback_document
from app.ml.name_matching.runtime import explain_similarity, get_local_name_matcher


@pytest.mark.parametrize(
    "candidate",
    [
        "غلام حسين",
        "GHULAM HUSSAIN",
        "Ghulam Hussain Insurance",
        "Payment to Ghulam",
    ],
)
def test_odoo_observed_ghulam_variants_remain_matches(candidate: str) -> None:
    result = explain_similarity("غلام", candidate)

    assert result.decision == "match"
    assert result.score >= 0.80


@pytest.mark.parametrize(
    "candidate",
    [
        "Hala",
        "Hala Trading",
        "Halamarket",
        "اسواق هلا الفرسان",
        "شركة هلا للخدمات",
        "Abu Halima",
        "Al-Ghamdi Trading",
        "Alam Trading",
        "MD Islam",
        "Other Receivable",
        "31978",
    ],
)
def test_odoo_mined_hard_negatives_are_rejected(candidate: str) -> None:
    result = explain_similarity("غلام", candidate)

    assert result.decision == "reject"
    assert result.score < 0.65


def test_feedback_corpus_contains_only_feature_vectors() -> None:
    document = load_feedback_document()
    serialized = str(document).lower()

    assert document["schema_version"] == 1
    assert document["source_summary"]["journal_rows_reviewed"] == 12_600
    assert document["source_summary"]["unique_partner_names_reviewed"] == 1_058
    assert document["source_summary"]["search_export_rows_reviewed"] == 37
    assert len(document["examples"]) == 85

    for example in document["examples"]:
        assert set(example) == {"label", "kind", "features"}
        assert example["label"] in (0, 1)
        assert len(example["features"]) == len(document["feature_names"])

    for forbidden in (
        "https://",
        "account.move",
        "journal entry",
        "partner_id",
        "رقم القيد",
    ):
        assert forbidden not in serialized


def test_model_metadata_includes_feedback_training_counts() -> None:
    matcher = get_local_name_matcher()

    assert matcher.model_version.startswith("hybrid-name-matcher-")
    assert matcher.accept_threshold == 0.80
