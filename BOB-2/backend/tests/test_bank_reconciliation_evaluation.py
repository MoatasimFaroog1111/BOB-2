from __future__ import annotations

from datetime import date, timedelta

from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_evaluation import (
    BankReconciliationEvaluationService,
    build_labeled_cases,
    time_series_split,
)


def _counter(
    account_id: int,
    label: str,
    amount: float,
    *,
    partner_id: int | None = None,
    partner_name: str = "",
    analytic_id: int | None = None,
):
    line = {
        "account_id": [account_id, label],
        "partner_id": [partner_id, partner_name] if partner_id else False,
        "balance": amount,
        "debit": max(amount, 0),
        "credit": abs(min(amount, 0)),
        "name": partner_name or label,
        "ref": "",
        "move_id": [1, "BNK/2026/0001"],
    }
    if analytic_id:
        line["analytic_distribution"] = {str(analytic_id): 100.0}
    return line


def _entry(index: int, occurred_on: str):
    move_name = f"BNK/2026/{index:04d}"
    kind = index % 3
    if kind == 0:
        text = f"STC internet monthly bill {move_name}"
        bank_amount = -1150.0
        counterparts = [
            _counter(
                400020,
                "400020 Telephone And Internet",
                1150.0,
                partner_id=7,
                partner_name="stc السعودية",
                analytic_id=2,
            )
        ]
    elif kind == 1:
        text = f"MOL iqama government fee {move_name}"
        bank_amount = -650.0
        counterparts = [
            _counter(
                400010,
                "400010 Iqama Fees",
                650.0,
                partner_id=9,
                partner_name="MOL",
                analytic_id=2,
            )
        ]
    else:
        text = f"INSTANT PAYMENT FEE 1.00 SAR VAT AMOUNT 0.15 SAR VAT% 15% {move_name}"
        bank_amount = -1.15
        counterparts = [
            _counter(400051, "400051 Other Bank Charges", 1.0),
            _counter(104041, "104041 VAT Input", 0.15),
        ]

    for line in counterparts:
        line["move_id"] = [index, move_name]
    return {
        "move_id": index,
        "move_name": move_name,
        "date": occurred_on,
        "bank_text": text,
        "bank_amount": bank_amount,
        "counterparts": counterparts,
    }


def _history(count: int = 45):
    start = date(2026, 1, 1)
    return [
        _entry(index, (start + timedelta(days=index - 1)).isoformat())
        for index in range(1, count + 1)
    ]


def test_labeled_cases_remove_post_generated_move_name_from_query():
    cases = build_labeled_cases(_history(30))

    assert len(cases) == 30
    assert "BNK/2026/0001" not in cases[0].transaction["description"]
    assert cases[0].target_account_id in {400010, 400020, 400051}


def test_time_series_split_keeps_whole_dates_disjoint_and_chronological():
    split = time_series_split(build_labeled_cases(_history(45)))

    train_dates = {row.occurred_on for row in split.train}
    validation_dates = {row.occurred_on for row in split.validation}
    test_dates = {row.occurred_on for row in split.test}

    assert train_dates.isdisjoint(validation_dates)
    assert train_dates.isdisjoint(test_dates)
    assert validation_dates.isdisjoint(test_dates)
    assert split.train[-1].occurred_on < split.validation[0].occurred_on
    assert split.validation[-1].occurred_on < split.test[0].occurred_on
    assert split.test[-1].occurred_on == "2026-02-14"


def test_untouched_evaluation_reports_account_partner_vat_and_analytic_accuracy():
    service = BankReconciliationEvaluationService(
        db=None,  # evaluate_historical is pure and never touches the DB/ERP resolver.
        context=SuggestionBatchContext(organization_id=1, company_id=1, bank_journal_id=10, bank_account_id=101001),
    )

    report = service.evaluate_historical(_history(45))

    assert report["status"] == "success"
    assert report["method"] == "strict_time_series_historical_consensus_v1"
    assert report["split"]["train"]["examples"] > report["split"]["validation"]["examples"]
    assert report["split"]["test"]["examples"] > 0
    assert report["leakage_checks"]["move_id_overlap"]["train_test"] == 0
    assert report["leakage_checks"]["accounting_date_overlap"]["validation_test"] == 0
    assert report["leakage_checks"]["strictly_chronological_boundaries"] is True
    assert report["untouched_test_contract"]["threshold_locked_before_test"] is True
    assert report["untouched_test_contract"]["test_labels_used_as_history"] is False

    test_metrics = report["untouched_test_metrics"]
    assert test_metrics["account"]["top1_accuracy"] >= 0.95
    assert test_metrics["account"]["top3_accuracy"] >= test_metrics["account"]["top1_accuracy"]
    assert test_metrics["partner"]["accuracy_on_labeled"] >= 0.95
    assert test_metrics["analytic"]["accuracy_on_labeled"] >= 0.95
    assert test_metrics["vat_detection"]["accuracy"] >= 0.95
    assert report["safe_to_post"] is False
    assert report["erp_mutation"] is False


def test_untouched_evaluation_rejects_too_small_history():
    service = BankReconciliationEvaluationService(
        db=None,
        context=SuggestionBatchContext(organization_id=1),
    )

    try:
        service.evaluate_historical(_history(20))
    except ValueError as exc:
        assert "At least 30" in str(exc)
    else:
        raise AssertionError("Expected small-history evaluation to be rejected")
