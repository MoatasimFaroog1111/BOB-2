"""Leakage-safe time-series evaluation for bank-reconciliation suggestions.

The evaluator intentionally measures the historical-consensus core without using
current BOB rules or the current semantic-memory corpus. Those sources may contain
knowledge created after a historical holdout date and would make an untouched-test
score optimistic unless every evidence item is versioned as-of that date.

Evaluation contract:
- build labels only from posted Odoo history;
- remove post-generated move names from model input;
- split by whole accounting dates so one date never spans partitions;
- calibrate the review threshold on Validation only;
- freeze that threshold before Test;
- use Train + Validation as the fixed historical corpus for Test;
- never add Test rows back to the corpus while Test is being scored;
- perform no ERP mutation or posting.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

from sqlalchemy.orm import Session

from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_features import (
    decimal_amount,
    detect_monetary_components,
    is_tax_account_label,
)
from app.services.bank_reconciliation_historical import (
    HistoricalSuggestionMatcher,
    OdooHistoricalBankEntryRepository,
)
from app.services.tenant_erp_service import tenant_erp_resolver

_MIN_CASES = 30
_MIN_DISTINCT_DATES = 3
_TRAIN_RATIO = 0.70
_VALIDATION_RATIO = 0.15
_TARGET_ACCEPTED_PRECISION = 0.90
_THRESHOLD_GRID = tuple(round(0.50 + step * 0.025, 3) for step in range(20))


@dataclass(frozen=True, slots=True)
class LabeledBankCase:
    move_id: int
    occurred_on: str
    transaction: dict[str, Any]
    target_account_id: int
    target_partner_id: int | None
    target_analytic_id: int | None
    target_vat_present: bool
    source_entry: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TimeSeriesSplit:
    train: tuple[LabeledBankCase, ...]
    validation: tuple[LabeledBankCase, ...]
    test: tuple[LabeledBankCase, ...]


def _m2o(value: Any) -> tuple[int | None, str]:
    # Odoo serializes an empty many2one as ``False``. Because bool is a subclass
    # of int in Python, handle it before the integer branch so an empty relation
    # never becomes a synthetic label with ID False/0 during evaluation.
    if value is None or value is False or value == "":
        return None, ""
    if isinstance(value, (list, tuple)) and value:
        try:
            identifier = int(value[0]) if value[0] else None
        except (TypeError, ValueError):
            identifier = None
        return identifier, str(value[1] if len(value) > 1 else "")
    if isinstance(value, int) and not isinstance(value, bool):
        return value, ""
    return None, ""


def _analytic_id(line: dict[str, Any]) -> int | None:
    direct_id, _label = _m2o(line.get("analytic_account_id"))
    if direct_id:
        return direct_id
    distribution = line.get("analytic_distribution")
    if isinstance(distribution, dict) and distribution:
        first_key = next(iter(distribution.keys()), None)
        if first_key:
            try:
                return int(str(first_key).split(",")[0])
            except (TypeError, ValueError):
                return None
    return None


def _line_amount(line: dict[str, Any]):
    if line.get("balance") is not None:
        return decimal_amount(line.get("balance"))
    return decimal_amount(line.get("debit")) - decimal_amount(line.get("credit"))


def _clean_bank_text(entry: dict[str, Any]) -> str:
    """Remove Odoo-generated move numbering from historical evaluation input."""
    text = str(entry.get("bank_text") or "")
    move_name = str(entry.get("move_name") or "").strip()
    if move_name:
        text = text.replace(move_name, " ")
    return " ".join(text.split()).strip()


def _primary_counterpart(entry: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[tuple[float, bool, dict[str, Any]]] = []
    for line in entry.get("counterparts") or []:
        account_id, account_label = _m2o(line.get("account_id"))
        if not account_id:
            continue
        magnitude = float(abs(_line_amount(line)))
        if magnitude <= 0:
            continue
        candidates.append((magnitude, is_tax_account_label(account_label), line))
    if not candidates:
        return None

    # A tax/VAT line is a split component, not the primary counterpart account,
    # whenever a non-tax counterpart exists. This is especially important for
    # bank charges such as 1.00 fee + 0.15 VAT.
    non_tax = [item for item in candidates if not item[1]]
    pool = non_tax or candidates
    pool.sort(key=lambda item: item[0], reverse=True)
    return pool[0][2]


def build_labeled_cases(historical: list[dict[str, Any]]) -> list[LabeledBankCase]:
    """Convert posted history into de-duplicated, pre-posting-like labeled cases."""
    cases: list[LabeledBankCase] = []
    seen_moves: set[int] = set()

    for entry in historical:
        try:
            move_id = int(entry.get("move_id") or 0)
        except (TypeError, ValueError):
            continue
        occurred_on = str(entry.get("date") or "").strip()
        if not move_id or not occurred_on or move_id in seen_moves:
            continue

        description = _clean_bank_text(entry)
        amount = float(decimal_amount(entry.get("bank_amount")))
        if not description or amount == 0:
            continue

        transaction = {
            "date": occurred_on,
            "description": description,
            "amount": amount,
            "row_number": move_id,
        }
        primary = _primary_counterpart(entry)
        if primary is None:
            continue
        account_id, _account_label = _m2o(primary.get("account_id"))
        if not account_id:
            continue
        partner_id, _partner_label = _m2o(primary.get("partner_id"))

        vat_present = False
        for line in entry.get("counterparts") or []:
            _line_account_id, line_account_label = _m2o(line.get("account_id"))
            if is_tax_account_label(line_account_label):
                vat_present = True
                break

        cases.append(
            LabeledBankCase(
                move_id=move_id,
                occurred_on=occurred_on,
                transaction=transaction,
                target_account_id=account_id,
                target_partner_id=partner_id,
                target_analytic_id=_analytic_id(primary),
                target_vat_present=vat_present,
                source_entry=entry,
            )
        )
        seen_moves.add(move_id)

    cases.sort(key=lambda case: (case.occurred_on, case.move_id))
    return cases


def _date_groups(cases: list[LabeledBankCase]) -> list[list[LabeledBankCase]]:
    groups: list[list[LabeledBankCase]] = []
    for case in cases:
        if not groups or groups[-1][0].occurred_on != case.occurred_on:
            groups.append([case])
        else:
            groups[-1].append(case)
    return groups


def _take_groups_near_target(
    groups: list[list[LabeledBankCase]],
    *,
    target_examples: int,
    leave_groups: int,
) -> int:
    """Return a whole-date group boundary closest to the requested example count."""
    if len(groups) <= leave_groups:
        return 0
    running = 0
    best_index = 1
    best_distance = float("inf")
    max_index = len(groups) - leave_groups
    for index in range(1, max_index + 1):
        running += len(groups[index - 1])
        distance = abs(running - target_examples)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def time_series_split(cases: list[LabeledBankCase]) -> TimeSeriesSplit:
    if len(cases) < _MIN_CASES:
        raise ValueError(
            f"At least {_MIN_CASES} labeled posted bank entries are required for an untouched time-series evaluation."
        )
    groups = _date_groups(sorted(cases, key=lambda case: (case.occurred_on, case.move_id)))
    if len(groups) < _MIN_DISTINCT_DATES:
        raise ValueError("At least three distinct accounting dates are required for time-series splitting.")

    total = len(cases)
    train_group_count = _take_groups_near_target(
        groups,
        target_examples=max(1, round(total * _TRAIN_RATIO)),
        leave_groups=2,
    )
    if train_group_count <= 0:
        raise ValueError("Unable to form a non-empty Train partition without crossing accounting dates.")

    remaining_groups = groups[train_group_count:]
    validation_group_count = _take_groups_near_target(
        remaining_groups,
        target_examples=max(1, round(total * _VALIDATION_RATIO)),
        leave_groups=1,
    )
    if validation_group_count <= 0:
        validation_group_count = 1

    train = tuple(case for group in groups[:train_group_count] for case in group)
    validation = tuple(
        case
        for group in remaining_groups[:validation_group_count]
        for case in group
    )
    test = tuple(
        case
        for group in remaining_groups[validation_group_count:]
        for case in group
    )
    if not train or not validation or not test:
        raise ValueError("Time-series split produced an empty Train, Validation, or Test partition.")
    return TimeSeriesSplit(train=train, validation=validation, test=test)


def _predict_cases(
    cases: tuple[LabeledBankCase, ...],
    history_pool: tuple[LabeledBankCase, ...],
    matcher: HistoricalSuggestionMatcher,
) -> list[dict[str, Any]]:
    historical = [case.source_entry for case in history_pool]
    rows: list[dict[str, Any]] = []
    for case in cases:
        suggestion = matcher.suggest(case.transaction, historical)
        rows.append({"case": case, "prediction": suggestion})
    return rows


def _top_account_ids(prediction: dict[str, Any] | None) -> set[int]:
    if not prediction:
        return set()
    result: set[int] = set()
    try:
        primary = int(prediction.get("suggested_account_id") or 0)
    except (TypeError, ValueError):
        primary = 0
    if primary:
        result.add(primary)
    for item in prediction.get("alternatives") or []:
        try:
            identifier = int(item.get("account_id") or 0)
        except (TypeError, ValueError):
            continue
        if identifier:
            result.add(identifier)
        if len(result) >= 3:
            break
    return result


def _confidence(prediction: dict[str, Any] | None) -> float:
    if not prediction:
        return 0.0
    try:
        return max(0.0, min(1.0, float(prediction.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _account_correct(row: dict[str, Any]) -> bool:
    prediction = row["prediction"] or {}
    try:
        return int(prediction.get("suggested_account_id") or 0) == int(row["case"].target_account_id)
    except (TypeError, ValueError):
        return False


def calibrate_review_threshold(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose a threshold from Validation only, prioritizing accountant-grade precision."""
    total = len(rows)
    if not total:
        return {
            "threshold": 1.0,
            "precision": 0.0,
            "coverage": 0.0,
            "accepted": 0,
            "policy": "no_validation_rows",
        }

    observed = {_confidence(row["prediction"]) for row in rows if row["prediction"]}
    thresholds = sorted(set(_THRESHOLD_GRID) | {round(value, 4) for value in observed})
    candidates: list[dict[str, Any]] = []
    for threshold in thresholds:
        accepted_rows = [
            row
            for row in rows
            if row["prediction"]
            and row["prediction"].get("suggested_account_id")
            and _confidence(row["prediction"]) >= threshold
        ]
        accepted = len(accepted_rows)
        correct = sum(1 for row in accepted_rows if _account_correct(row))
        precision = correct / accepted if accepted else 0.0
        coverage = accepted / total
        candidates.append(
            {
                "threshold": float(threshold),
                "precision": precision,
                "coverage": coverage,
                "accepted": accepted,
                "score": precision * sqrt(coverage) if coverage > 0 else 0.0,
            }
        )

    precision_candidates = [
        candidate
        for candidate in candidates
        if candidate["accepted"] >= min(5, total)
        and candidate["precision"] >= _TARGET_ACCEPTED_PRECISION
    ]
    if precision_candidates:
        best = max(
            precision_candidates,
            key=lambda candidate: (candidate["coverage"], candidate["precision"], candidate["threshold"]),
        )
        policy = "max_coverage_at_or_above_90pct_validation_precision"
    else:
        best = max(
            candidates,
            key=lambda candidate: (candidate["score"], candidate["precision"], candidate["coverage"]),
        )
        policy = "best_precision_coverage_tradeoff_below_90pct_target"

    return {
        "threshold": round(float(best["threshold"]), 4),
        "precision": round(float(best["precision"]), 4),
        "coverage": round(float(best["coverage"]), 4),
        "accepted": int(best["accepted"]),
        "policy": policy,
        "target_precision": _TARGET_ACCEPTED_PRECISION,
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _pct(value: float) -> float:
    return round(float(value) * 100.0, 2)


def score_predictions(rows: list[dict[str, Any]], *, review_threshold: float) -> dict[str, Any]:
    total = len(rows)
    account_resolved = 0
    account_correct = 0
    account_top3 = 0
    partner_support = partner_resolved = partner_correct = 0
    analytic_support = analytic_resolved = analytic_correct = 0
    vat_tp = vat_tn = vat_fp = vat_fn = 0
    joint_correct = 0
    accepted = accepted_correct = 0
    error_samples: list[dict[str, Any]] = []

    for row in rows:
        case: LabeledBankCase = row["case"]
        prediction = row["prediction"] or {}
        predicted_account = int(prediction.get("suggested_account_id") or 0)
        account_is_correct = predicted_account == case.target_account_id
        if predicted_account:
            account_resolved += 1
        if account_is_correct:
            account_correct += 1
        if case.target_account_id in _top_account_ids(prediction):
            account_top3 += 1

        predicted_partner = int(prediction.get("suggested_partner_id") or 0) or None
        partner_is_correct = True
        if case.target_partner_id is not None:
            partner_support += 1
            if predicted_partner is not None:
                partner_resolved += 1
            partner_is_correct = predicted_partner == case.target_partner_id
            if partner_is_correct:
                partner_correct += 1

        predicted_analytic = int(prediction.get("suggested_analytic_account_id") or 0) or None
        analytic_is_correct = True
        if case.target_analytic_id is not None:
            analytic_support += 1
            if predicted_analytic is not None:
                analytic_resolved += 1
            analytic_is_correct = predicted_analytic == case.target_analytic_id
            if analytic_is_correct:
                analytic_correct += 1

        components = detect_monetary_components(case.transaction)
        predicted_vat = float(components.get("vat_amount") or 0.0) > 0
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

        if predicted_account and _confidence(prediction) >= review_threshold:
            accepted += 1
            if account_is_correct:
                accepted_correct += 1

        if not account_is_correct and len(error_samples) < 12:
            error_samples.append(
                {
                    "move_id": case.move_id,
                    "date": case.occurred_on,
                    "target_account_id": case.target_account_id,
                    "predicted_account_id": predicted_account or None,
                    "confidence": round(_confidence(prediction), 4),
                }
            )

    vat_precision = _ratio(vat_tp, vat_tp + vat_fp)
    vat_recall = _ratio(vat_tp, vat_tp + vat_fn)
    vat_f1 = (
        round(2 * vat_precision * vat_recall / (vat_precision + vat_recall), 4)
        if vat_precision + vat_recall
        else 0.0
    )

    account_accuracy = _ratio(account_correct, total)
    account_top3_accuracy = _ratio(account_top3, total)
    partner_accuracy = _ratio(partner_correct, partner_support)
    analytic_accuracy = _ratio(analytic_correct, analytic_support)
    vat_accuracy = _ratio(vat_tp + vat_tn, total)
    joint_accuracy = _ratio(joint_correct, total)
    accepted_precision = _ratio(accepted_correct, accepted)
    accepted_coverage = _ratio(accepted, total)

    return {
        "sample_count": total,
        "account": {
            "top1_accuracy": account_accuracy,
            "top1_accuracy_pct": _pct(account_accuracy),
            "top3_accuracy": account_top3_accuracy,
            "top3_accuracy_pct": _pct(account_top3_accuracy),
            "coverage": _ratio(account_resolved, total),
            "coverage_pct": _pct(_ratio(account_resolved, total)),
        },
        "partner": {
            "accuracy_on_labeled": partner_accuracy,
            "accuracy_on_labeled_pct": _pct(partner_accuracy),
            "labeled_support": partner_support,
            "coverage_on_labeled": _ratio(partner_resolved, partner_support),
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
        },
        "strict_joint_accuracy": joint_accuracy,
        "strict_joint_accuracy_pct": _pct(joint_accuracy),
        "review_gate": {
            "threshold": round(float(review_threshold), 4),
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

    return {
        "train": part(split.train),
        "validation": part(split.validation),
        "test": part(split.test),
    }


def _leakage_checks(split: TimeSeriesSplit) -> dict[str, Any]:
    train_ids = {case.move_id for case in split.train}
    validation_ids = {case.move_id for case in split.validation}
    test_ids = {case.move_id for case in split.test}
    train_dates = {case.occurred_on for case in split.train}
    validation_dates = {case.occurred_on for case in split.validation}
    test_dates = {case.occurred_on for case in split.test}
    chronological = (
        split.train[-1].occurred_on < split.validation[0].occurred_on
        and split.validation[-1].occurred_on < split.test[0].occurred_on
    )
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
        "strictly_chronological_boundaries": chronological,
        "post_generated_move_name_removed_from_query": True,
        "validation_used_for_threshold_calibration": True,
        "test_used_for_threshold_calibration": False,
        "test_rows_added_to_test_history_corpus": False,
    }


class BankReconciliationEvaluationService:
    """Application orchestrator for a read-only, untouched historical evaluation."""

    def __init__(
        self,
        db: Session,
        context: SuggestionBatchContext,
        *,
        history_repository: OdooHistoricalBankEntryRepository | None = None,
        matcher: HistoricalSuggestionMatcher | None = None,
    ) -> None:
        self.db = db
        self.context = context
        self.history_repository = history_repository or OdooHistoricalBankEntryRepository()
        self.matcher = matcher or HistoricalSuggestionMatcher()

    def evaluate_historical(self, historical: list[dict[str, Any]]) -> dict[str, Any]:
        cases = build_labeled_cases(historical)
        split = time_series_split(cases)

        validation_rows = _predict_cases(split.validation, split.train, self.matcher)
        calibration = calibrate_review_threshold(validation_rows)
        threshold = float(calibration["threshold"])
        validation_metrics = score_predictions(validation_rows, review_threshold=threshold)

        # Standard final-fit contract: after model-selection/calibration is locked,
        # Validation may join the historical corpus. Test labels remain completely
        # excluded from the fixed Test-time corpus.
        final_history_pool = tuple((*split.train, *split.validation))
        test_rows = _predict_cases(split.test, final_history_pool, self.matcher)
        test_metrics = score_predictions(test_rows, review_threshold=threshold)

        split_summary = _split_summary(split)
        leakage = _leakage_checks(split)
        test_summary = test_metrics["account"]
        return {
            "status": "success",
            "method": "strict_time_series_historical_consensus_v1",
            "dataset": {
                "historical_entries_read": len(historical),
                "labeled_cases": len(cases),
                "date_from": cases[0].occurred_on if cases else None,
                "date_to": cases[-1].occurred_on if cases else None,
            },
            "split": split_summary,
            "leakage_checks": leakage,
            "calibration": calibration,
            "validation_metrics": validation_metrics,
            "untouched_test_metrics": test_metrics,
            "accuracy_summary_pct": {
                "account_top1": test_summary["top1_accuracy_pct"],
                "account_top3": test_summary["top3_accuracy_pct"],
                "partner_on_labeled": test_metrics["partner"]["accuracy_on_labeled_pct"],
                "vat_detection": test_metrics["vat_detection"]["accuracy_pct"],
                "analytic_on_labeled": test_metrics["analytic"]["accuracy_on_labeled_pct"],
                "strict_joint": test_metrics["strict_joint_accuracy_pct"],
            },
            "untouched_test_contract": {
                "threshold_locked_before_test": True,
                "matcher_parameters_changed_on_test": False,
                "test_labels_used_as_history": False,
                "final_history_corpus": "train_plus_validation_only",
                "test_partition": "latest_whole_accounting_dates",
            },
            "scope": {
                "organization_id": self.context.organization_id,
                "company_id": self.context.company_id,
                "bank_journal_id": self.context.bank_journal_id,
                "bank_account_id": self.context.bank_account_id,
            },
            "excluded_from_untouched_score": {
                "current_bob_bank_rules": (
                    "Excluded because current approved rules can encode knowledge created after historical holdout dates."
                ),
                "current_semantic_memory": (
                    "Excluded because the current memory corpus is not yet snapshotted/versioned as-of each holdout boundary."
                ),
            },
            "safe_to_post": False,
            "erp_mutation": False,
        }

    def evaluate(self) -> dict[str, Any]:
        _connection, erp = tenant_erp_resolver.resolve(self.db, self.context.organization_id)
        historical = self.history_repository.fetch(erp, self.context)
        return self.evaluate_historical(historical)
