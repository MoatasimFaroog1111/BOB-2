from pathlib import Path

import pytest

from app.ml.accounting_intelligence.persisted_bundle import (
    PersistedAccountingModelError,
    VerifiedAccountingBundleLoader,
)
from app.ml.accounting_intelligence.prediction_gate import AccountingPredictionGate
from app.services.accounting_persisted_inference import AccountingPersistedInferenceService


class _LegacyStub:
    def predict(self, **_kwargs):
        return {"confidence": 0.42, "warnings": [], "partners": []}

    def status(self, **_kwargs):
        return {"status": "success", "learning_examples": 0, "auto_posting": False}


class _FailIfCalledPredictor:
    class _Loader:
        @staticmethod
        def status():
            return {"available": True, "verified": True, "model_version": "accounting-ml-v2.0.0"}

    loader = _Loader()

    def predict(self, **_kwargs):
        raise AssertionError("persisted predictor must not run for non-document channels")


def _candidate(
    label: str,
    score: float,
    identifier: int | None = 1,
    **extra,
):
    row = {
        "label": label,
        "model_score": score,
        "selected": True,
        "rank": 1,
        "live_reference_resolved": identifier is not None,
        **extra,
    }
    if identifier is not None:
        row["id"] = identifier
    return row


def test_verified_loader_rejects_tampered_artifact_before_deserialization(tmp_path: Path):
    artifact = tmp_path / "bundle.joblib"
    artifact.write_bytes(b"this is not the reviewed model bundle")
    loader = VerifiedAccountingBundleLoader(
        path=artifact,
        expected_sha256="0" * 64,
        expected_model_version="accounting-ml-v2.0.0",
    )
    with pytest.raises(PersistedAccountingModelError, match="SHA-256"):
        loader.load()


def test_non_document_channel_never_invokes_persisted_attachment_model():
    service = AccountingPersistedInferenceService(
        db=None,
        persisted_predictor=_FailIfCalledPredictor(),
        legacy_service=_LegacyStub(),
    )
    result = service.predict(
        organization_id=1,
        text="pay the monthly internet bill",
        channel="chat",
        amount=100.0,
    )
    assert result["primary_engine"] == "historical_semantic_structured"
    assert result["persisted_model_skipped"]["reason"] == "channel_outside_attachment_training_contract"


def test_prediction_gate_blocks_low_score_and_missing_amount():
    prediction = {
        "move_type": [_candidate("entry", 0.90)],
        "journals": [_candidate("BNK1", 0.60, 13, type="bank")],
        "debit_accounts": [_candidate("400020", 0.80, 101)],
        "credit_accounts": [_candidate("101001", 0.90, 102)],
    }
    result = AccountingPredictionGate().evaluate(prediction, amount=None)
    assert result["draft_eligible"] is False
    assert result["review_required"] is True
    assert result["auto_post_allowed"] is False
    codes = {item["code"] for item in result["findings"]}
    assert "JOURNAL_LOW_SCORE" in codes
    assert "AMOUNT_REQUIRED_FOR_DRAFT" in codes


def test_prediction_gate_allows_high_score_single_sided_draft_proposal_only():
    prediction = {
        "move_type": [_candidate("entry", 0.95)],
        "journals": [_candidate("BNK1", 0.92, 13, type="bank")],
        "debit_accounts": [_candidate("400020", 0.88, 101)],
        "credit_accounts": [_candidate("101001", 0.93, 102)],
    }
    result = AccountingPredictionGate().evaluate(prediction, amount=1150.0)
    assert result["draft_eligible"] is True
    assert result["review_required"] is False
    assert result["auto_post_allowed"] is False
