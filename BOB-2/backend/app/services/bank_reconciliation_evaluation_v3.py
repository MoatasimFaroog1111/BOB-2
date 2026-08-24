"""Leakage-safe Phase 4 evaluator for bank-reconciliation intelligence.

The evaluator keeps the same public response shape consumed by the existing accuracy
page while adding V4 identity/candidate diagnostics.  Validation alone calibrates the
account trust gate at a 99% precision target and a separate partner-resolution gate.
The latest whole accounting dates remain untouched Test data and never enter history
or calibration.
"""

from __future__ import annotations

from dataclasses import replace
from math import sqrt
from typing import Any

from sqlalchemy.orm import Session

from app.services.bank_reconciliation_accuracy_v4 import HistoricalSuggestionMatcherV4
from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_evaluation import (
    LabeledBankCase,
    TimeSeriesSplit,
    build_labeled_cases,
    time_series_split,
)
from app.services.bank_reconciliation_features import transaction_category, transaction_text
from app.services.bank_reconciliation_historical import OdooHistoricalBankEntryRepository
from app.services.tenant_erp_service import tenant_erp_resolver

_TARGET_ACCEPTED_PRECISION = 0.99
_TARGET_PARTNER_PRECISION = 0.90
_THRESHOLD_GRID = tuple(round(0.40 + step * 0.025, 3) for step in range(25))
_MIN_CATEGORY_VALIDATION_ROWS = 12
_MIN_ACCEPTED_FOR_CALIBRATION = 3


def _partner_labelled_cases(historical: list[dict[str, Any]]) -> list[LabeledBankCase]:
    cases = build_labeled_cases(historical)
    enriched: list[LabeledBankCase] = []
    for case in cases:
        if case.target_partner_id is not None:
            enriched.append(case)
            continue
        raw = case.source_entry.get("bank_partner_id")
        try:
            partner_id = int(raw) if raw else None
        except (TypeError, ValueError):
            partner_id = None
        enriched.append(replace(case, target_partner_id=partner_id))
    return enriched


def _predict_cases(
    cases: tuple[LabeledBankCase, ...],
    history_pool: tuple[LabeledBankCase, ...],
    matcher: HistoricalSuggestionMatcherV4,
) -> list[dict[str, Any]]:
    historical = [case.source_entry for case in history_pool]
    return [{"case": case, "prediction": matcher.suggest(case.transaction, historical)} for case in cases]


def _confidence(prediction: dict[str, Any] | None) -> float:
    if not prediction:
        return 0.0
    try:
        return max(0.0, min(1.0, float(prediction.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _partner_candidate(prediction: dict[str, Any] | None) -> tuple[int | None, float]:
    if not prediction:
        return None, 0.0
    resolution = prediction.get("partner_resolution") or {}
    raw = resolution.get("candidate_partner_id") or prediction.get("suggested_partner_id")
    try:
        partner_id = int(raw) if raw else None
    except (TypeError, ValueError):
        partner_id = None
    try:
        confidence = max(0.0, min(1.0, float(resolution.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return partner_id, confidence


def _account_correct(row: dict[str, Any]) -> bool:
    prediction = row.get("prediction") or {}
    try:
        return int(prediction.get("suggested_account_id") or 0) == int(row["case"].target_account_id)
    except (TypeError, ValueError):
        return False


def _row_category(row: dict[str, Any]) -> str:
    case: LabeledBankCase = row["case"]
    return transaction_category(transaction_text(case.transaction))


def _top_account_ids(prediction: dict[str, Any] | None) -> list[int]:
    if not prediction:
        return []
    result: list[int] = []
    raw_values: list[Any] = [prediction.get("suggested_account_id")]
    raw_values.extend(item.get("account_id") for item in prediction.get("alternatives") or [])
    for raw in raw_values:
        try:
            identifier = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if identifier and identifier not in result:
            result.append(identifier)
        if len(result) >= 3:
            break
    return result


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _pct(value: float) -> float:
    return round(float(value) * 100.0, 2)


def _calibrate_binary_gate(
    rows: list[dict[str, Any]],
    *,
    confidence_getter,
    correctness_getter,
    resolvable_getter,
    target_precision: float,
) -> dict[str, Any]:
    observed = {
        round(float(confidence_getter(row)), 4)
        for row in rows
        if resolvable_getter(row)
    }
    thresholds = sorted(set(_THRESHOLD_GRID) | observed | {1.0})
    candidates: list[dict[str, Any]] = []
    total = len(rows)
    for threshold in thresholds:
        accepted_rows = [
            row
            for row in rows
            if resolvable_getter(row) and float(confidence_getter(row)) >= threshold
        ]
        accepted = len(accepted_rows)
        correct = sum(1 for row in accepted_rows if correctness_getter(row))
        precision = correct / accepted if accepted else 0.0
        coverage = accepted / total if total else 0.0
        candidates.append(
            {
                "threshold": float(threshold),
                "precision": precision,
                "coverage": coverage,
                "accepted": accepted,
                "score": precision * sqrt(coverage) if coverage else 0.0,
            }
        )
    eligible = [
        item
        for item in candidates
        if item["accepted"] >= min(_MIN_ACCEPTED_FOR_CALIBRATION, max(1, total))
        and item["precision"] >= target_precision
    ]
    if eligible:
        best = max(eligible, key=lambda item: (item["coverage"], item["precision"], item["threshold"]))
        target_met = True
    else:
        nonempty = [item for item in candidates if item["accepted"] > 0]
        best = max(
            nonempty or candidates,
            key=lambda item: (item["precision"], item["coverage"], item["threshold"]),
        )
        target_met = False
    return {
        "threshold": round(float(best["threshold"]), 4),
        "precision": round(float(best["precision"]), 4),
        "coverage": round(float(best["coverage"]), 4),
        "accepted": int(best["accepted"]),
        "target_met": target_met,
        "target_precision": target_precision,
    }


def calibrate_review_policy_v3(rows: list[dict[str, Any]]) -> dict[str, Any]:
    global_gate = _calibrate_binary_gate(
        rows,
        confidence_getter=lambda row: _confidence(row.get("prediction")),
        correctness_getter=_account_correct,
        resolvable_getter=lambda row: bool((row.get("prediction") or {}).get("suggested_account_id")),
        target_precision=_TARGET_ACCEPTED_PRECISION,
    )
    category_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        category_rows.setdefault(_row_category(row), []).append(row)

    thresholds: dict[str, float] = {}
    diagnostics: dict[str, dict[str, Any]] = {}
    for category, subset in sorted(category_rows.items()):
        if len(subset) < _MIN_CATEGORY_VALIDATION_ROWS:
            continue
        gate = _calibrate_binary_gate(
            subset,
            confidence_getter=lambda row: _confidence(row.get("prediction")),
            correctness_getter=_account_correct,
            resolvable_getter=lambda row: bool((row.get("prediction") or {}).get("suggested_account_id")),
            target_precision=_TARGET_ACCEPTED_PRECISION,
        )
        diagnostics[category] = {**gate, "validation_rows": len(subset)}
        if gate["target_met"]:
            thresholds[category] = float(gate["threshold"])

    partner_labeled = [row for row in rows if row["case"].target_partner_id is not None]
    partner_gate = _calibrate_binary_gate(
        partner_labeled,
        confidence_getter=lambda row: _partner_candidate(row.get("prediction"))[1],
        correctness_getter=lambda row: _partner_candidate(row.get("prediction"))[0] == row["case"].target_partner_id,
        resolvable_getter=lambda row: _partner_candidate(row.get("prediction"))[0] is not None,
        target_precision=_TARGET_PARTNER_PRECISION,
    )

    return {
        **global_gate,
        "policy": "category_aware_max_coverage_at_99pct_validation_precision",
        "target_precision": _TARGET_ACCEPTED_PRECISION,
        "threshold_by_category": thresholds,
        "category_calibration": diagnostics,
        "partner_gate": partner_gate,
        "calibrated_from": "validation_only",
    }


def _threshold_for_row(row: dict[str, Any], policy: dict[str, Any]) -> float:
    category = _row_category(row)
    thresholds = policy.get("threshold_by_category") or {}
    if category in thresholds:
        return float(thresholds[category])
    return float(policy.get("threshold") or 1.0)


def score_predictions_v3(rows: list[dict[str, Any]], *, review_policy: dict[str, Any]) -> dict[str, Any]:
    total = len(rows)
    account_resolved = account_correct = account_top3 = 0
    partner_support = partner_resolved = partner_correct = 0
    analytic_support = analytic_resolved = analytic_correct = 0
    vat_tp = vat_tn = vat_fp = vat_fn = 0
    joint_correct = 0
    accepted = accepted_correct = 0
    partner_gate_accepted = partner_gate_correct = 0
    candidate_recall_failures = 0
    error_samples: list[dict[str, Any]] = []

    partner_threshold = float((review_policy.get("partner_gate") or {}).get("threshold") or 1.0)

    for row in rows:
        case: LabeledBankCase = row["case"]
        prediction = row.get("prediction") or {}
        try:
            predicted_account = int(prediction.get("suggested_account_id") or 0)
        except (TypeError, ValueError):
            predicted_account = 0
        account_is_correct = predicted_account == case.target_account_id
        top3 = _top_account_ids(prediction)
        if predicted_account:
            account_resolved += 1
        if account_is_correct:
            account_correct += 1
        if case.target_account_id in top3:
            account_top3 += 1
        else:
            candidate_recall_failures += 1

        try:
            predicted_partner = int(prediction.get("suggested_partner_id") or 0) or None
        except (TypeError, ValueError):
            predicted_partner = None
        partner_is_correct = True
        if case.target_partner_id is not None:
            partner_support += 1
            if predicted_partner is not None:
                partner_resolved += 1
            partner_is_correct = predicted_partner == case.target_partner_id
            if partner_is_correct:
                partner_correct += 1
            candidate_partner, candidate_confidence = _partner_candidate(prediction)
            if candidate_partner is not None and candidate_confidence >= partner_threshold:
                partner_gate_accepted += 1
                if candidate_partner == case.target_partner_id:
                    partner_gate_correct += 1

        try:
            predicted_analytic = int(prediction.get("suggested_analytic_account_id") or 0) or None
        except (TypeError, ValueError):
            predicted_analytic = None
        analytic_is_correct = True
        if case.target_analytic_id is not None:
            analytic_support += 1
            if predicted_analytic is not None:
                analytic_resolved += 1
            analytic_is_correct = predicted_analytic == case.target_analytic_id
            if analytic_is_correct:
                analytic_correct += 1

        predicted_vat = bool(prediction.get("predicted_vat_present", False))
        if case.target_vat_present and predicted_vat:
            vat_tp += 1
        elif not case.target_vat_present and not predicted_vat:
            vat_tn += 1
        elif not case.target_vat_present and predicted_vat:
            vat_fp += 1
        else:
            vat_fn += 1
        vat_is_correct = predicted_vat == case.target_vat_present

        if account_is_correct and partner_is_correct and analytic_is_correct and vat_is_correct:
            joint_correct += 1

        threshold = _threshold_for_row(row, review_policy)
        if predicted_account and _confidence(prediction) >= threshold:
            accepted += 1
            if account_is_correct:
                accepted_correct += 1

        if not account_is_correct and len(error_samples) < 20:
            error_samples.append(
                {
                    "move_id": case.move_id,
                    "date": case.occurred_on,
                    "category": _row_category(row),
                    "target_account_id": case.target_account_id,
                    "predicted_account_id": predicted_account or None,
                    "predicted_partner_id": predicted_partner,
                    "confidence": round(_confidence(prediction), 4),
                    "top3_account_ids": top3,
                    "candidate_recall_failure": case.target_account_id not in top3,
                }
            )

    vat_precision = _ratio(vat_tp, vat_tp + vat_fp)
    vat_recall = _ratio(vat_tp, vat_tp + vat_fn)
    vat_f1 = round(2 * vat_precision * vat_recall / (vat_precision + vat_recall), 4) if vat_precision + vat_recall else 0.0
    account_accuracy = _ratio(account_correct, total)
    account_top3_accuracy = _ratio(account_top3, total)
    partner_accuracy = _ratio(partner_correct, partner_support)
    partner_precision = _ratio(partner_correct, partner_resolved)
    analytic_accuracy = _ratio(analytic_correct, analytic_support)
    vat_accuracy = _ratio(vat_tp + vat_tn, total)
    joint_accuracy = _ratio(joint_correct, total)
    accepted_precision = _ratio(accepted_correct, accepted)
    accepted_coverage = _ratio(accepted, total)
    partner_gate_precision = _ratio(partner_gate_correct, partner_gate_accepted)
    partner_gate_coverage = _ratio(partner_gate_accepted, partner_support)

    return {
        "sample_count": total,
        "account": {
            "top1_accuracy": account_accuracy,
            "top1_accuracy_pct": _pct(account_accuracy),
            "top3_accuracy": account_top3_accuracy,
            "top3_accuracy_pct": _pct(account_top3_accuracy),
            "coverage": _ratio(account_resolved, total),
            "coverage_pct": _pct(_ratio(account_resolved, total)),
            "candidate_recall_failures": candidate_recall_failures,
        },
        "partner": {
            "accuracy_on_labeled": partner_accuracy,
            "accuracy_on_labeled_pct": _pct(partner_accuracy),
            "precision_on_resolved": partner_precision,
            "precision_on_resolved_pct": _pct(partner_precision),
            "labeled_support": partner_support,
            "resolved_support": partner_resolved,
            "coverage_on_labeled": _ratio(partner_resolved, partner_support),
            "gate_threshold": round(partner_threshold, 4),
            "gate_precision": partner_gate_precision,
            "gate_precision_pct": _pct(partner_gate_precision),
            "gate_coverage": partner_gate_coverage,
            "gate_coverage_pct": _pct(partner_gate_coverage),
            "gate_accepted": partner_gate_accepted,
        },
        "analytic": {
            "accuracy_on_labeled": analytic_accuracy,
            "accuracy_on_labeled_pct": _pct(analytic_accuracy),
            "labeled_support": analytic_support,
            "coverage_on_labeled": _ratio(analytic_resolved, analytic_support),
        },
        "vat_detection": {
            "accuracy": vat_accuracy,
            "accuracy_pct": _pct(vat_accuracy),
            "precision": vat_precision,
            "recall": vat_recall,
            "f1": vat_f1,
            "positive_support": vat_tp + vat_fn,
            "tp": vat_tp,
            "tn": vat_tn,
            "fp": vat_fp,
            "fn": vat_fn,
            "method": "v3_protected_historical_vat_propensity",
        },
        "strict_joint_accuracy": joint_accuracy,
        "strict_joint_accuracy_pct": _pct(joint_accuracy),
        "review_gate": {
            "threshold": round(float(review_policy.get("threshold") or 1.0), 4),
            "threshold_mode": "category_aware",
            "threshold_by_category": review_policy.get("threshold_by_category") or {},
            "target_precision": _TARGET_ACCEPTED_PRECISION,
            "accepted_account_precision": accepted_precision,
            "accepted_account_precision_pct": _pct(accepted_precision),
            "accepted_coverage": accepted_coverage,
            "accepted_coverage_pct": _pct(accepted_coverage),
            "accepted_count": accepted,
        },
        "error_samples": error_samples,
    }


def _split_summary(split: TimeSeriesSplit) -> dict[str, Any]:
    def part(rows: tuple[LabeledBankCase, ...]) -> dict[str, Any]:
        return {
            "examples": len(rows),
            "date_from": rows[0].occurred_on if rows else None,
            "date_to": rows[-1].occurred_on if rows else None,
            "distinct_dates": len({row.occurred_on for row in rows}),
        }
    return {"train": part(split.train), "validation": part(split.validation), "test": part(split.test)}


def _leakage_checks(split: TimeSeriesSplit) -> dict[str, Any]:
    train_ids = {case.move_id for case in split.train}
    validation_ids = {case.move_id for case in split.validation}
    test_ids = {case.move_id for case in split.test}
    train_dates = {case.occurred_on for case in split.train}
    validation_dates = {case.occurred_on for case in split.validation}
    test_dates = {case.occurred_on for case in split.test}
    return {
        "move_id_overlap": {
            "train_validation": len(train_ids & validation_ids),
            "train_test": len(train_ids & test_ids),
            "validation_test": len(validation_ids & test_ids),
        },
        "accounting_date_overlap": {
            "train_validation": len(train_dates & validation_dates),
            "train_test": len(train_dates & test_dates),
            "validation_test": len(validation_dates & test_dates),
        },
        "strictly_chronological_boundaries": (
            split.train[-1].occurred_on < split.validation[0].occurred_on
            and split.validation[-1].occurred_on < split.test[0].occurred_on
        ),
        "post_generated_move_name_removed_from_query": True,
        "future_dated_history_filtered_by_matcher": True,
        "validation_used_for_threshold_calibration": True,
        "test_used_for_threshold_calibration": False,
        "test_rows_added_to_test_history_corpus": False,
        "vat_inference_uses_test_labels": False,
        "partner_identity_resolver_uses_test_labels": False,
        "account_candidate_generator_uses_test_labels": False,
    }


class BankReconciliationEvaluationServiceV3:
    """Read-only untouched evaluator for V4 bank intelligence."""

    def __init__(
        self,
        db: Session,
        context: SuggestionBatchContext,
        *,
        history_repository: OdooHistoricalBankEntryRepository | None = None,
        matcher: HistoricalSuggestionMatcherV4 | None = None,
    ) -> None:
        self.db = db
        self.context = context
        self.history_repository = history_repository or OdooHistoricalBankEntryRepository()
        self.matcher = matcher or HistoricalSuggestionMatcherV4()

    def evaluate_historical(self, historical: list[dict[str, Any]]) -> dict[str, Any]:
        cases = _partner_labelled_cases(historical)
        split = time_series_split(cases)

        validation_rows = _predict_cases(split.validation, split.train, self.matcher)
        calibration = calibrate_review_policy_v3(validation_rows)
        validation_metrics = score_predictions_v3(validation_rows, review_policy=calibration)

        final_history_pool = tuple((*split.train, *split.validation))
        test_rows = _predict_cases(split.test, final_history_pool, self.matcher)
        test_metrics = score_predictions_v3(test_rows, review_policy=calibration)
        account = test_metrics["account"]

        return {
            "status": "success",
            "method": "strict_time_series_identity_candidate_calibration_v3",
            "engine_version": "v4_identity_candidate_calibration",
            "dataset": {
                "historical_entries_read": len(historical),
                "labeled_cases": len(cases),
                "date_from": cases[0].occurred_on if cases else None,
                "date_to": cases[-1].occurred_on if cases else None,
            },
            "split": _split_summary(split),
            "leakage_checks": _leakage_checks(split),
            "calibration": calibration,
            "validation_metrics": validation_metrics,
            "untouched_test_metrics": test_metrics,
            "accuracy_summary_pct": {
                "account_top1": account["top1_accuracy_pct"],
                "account_top3": account["top3_accuracy_pct"],
                "partner_on_labeled": test_metrics["partner"]["accuracy_on_labeled_pct"],
                "vat_detection": test_metrics["vat_detection"]["accuracy_pct"],
                "analytic_on_labeled": test_metrics["analytic"]["accuracy_on_labeled_pct"],
                "strict_joint": test_metrics["strict_joint_accuracy_pct"],
            },
            "untouched_test_contract": {
                "threshold_locked_before_test": True,
                "partner_threshold_locked_before_test": True,
                "matcher_parameters_changed_on_test": False,
                "test_labels_used_as_history": False,
                "final_history_corpus": "train_plus_validation_only",
                "test_partition": "latest_whole_accounting_dates",
                "accepted_precision_target": _TARGET_ACCEPTED_PRECISION,
                "partner_precision_target": _TARGET_PARTNER_PRECISION,
                "partner_labels": "counterpart_then_bank_line_fallback",
                "vat_predictor": "v3_protected_train_validation_evidence_only",
            },
            "scope": {
                "organization_id": self.context.organization_id,
                "company_id": self.context.company_id,
                "bank_journal_id": self.context.bank_journal_id,
                "bank_account_id": self.context.bank_account_id,
            },
            "excluded_from_untouched_score": {
                "current_bob_bank_rules": "Excluded until historically versioned as-of each holdout boundary.",
                "current_semantic_memory": "Excluded until the memory corpus is snapshotted as-of each holdout boundary.",
            },
            "safe_to_post": False,
            "erp_mutation": False,
        }

    def evaluate(self) -> dict[str, Any]:
        _connection, erp = tenant_erp_resolver.resolve(self.db, self.context.organization_id)
        historical = self.history_repository.fetch(erp, self.context)
        return self.evaluate_historical(historical)


BankReconciliationEvaluationService = BankReconciliationEvaluationServiceV3

__all__ = [
    "BankReconciliationEvaluationService",
    "BankReconciliationEvaluationServiceV3",
    "calibrate_review_policy_v3",
    "score_predictions_v3",
]
