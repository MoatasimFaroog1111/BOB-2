from __future__ import annotations

from datetime import date, timedelta

from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_evaluation_v2 import BankReconciliationEvaluationServiceV2
from app.services.bank_reconciliation_historical import HistoricalSuggestionMatcher


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
        "name": partner_name or "counterpart",
        "ref": "",
        "move_id": [1, "BNK/2026/0001"],
    }
    if analytic_id:
        line["analytic_distribution"] = {str(analytic_id): 100.0}
    return line


def _history_entry(
    move_id: int,
    occurred_on: str,
    text: str,
    amount: float,
    counterparts: list[dict],
    *,
    bank_partner_id: int | None = None,
    bank_partner_label: str = "",
):
    move_name = f"BNK/2026/{move_id:04d}"
    for line in counterparts:
        line["move_id"] = [move_id, move_name]
    return {
        "move_id": move_id,
        "move_name": move_name,
        "date": occurred_on,
        "bank_text": f"{text} {move_name}",
        "bank_amount": amount,
        "bank_partner_id": bank_partner_id,
        "bank_partner_label": bank_partner_label,
        "counterparts": counterparts,
    }


def test_v3_recovers_partner_from_posted_bank_line_when_counterpart_partner_is_empty():
    historical = [
        _history_entry(
            1,
            "2026-05-01",
            "MOATASIM FAROOG MOHAMMED NOOR outgoing IPS local transfer",
            -5000.0,
            [_counter(63, "102014 Other Receivable", 5000.0)],
            bank_partner_id=84,
            bank_partner_label="Petty Cash-Moatasim Faroog Mohammed Noor",
        ),
        _history_entry(
            2,
            "2026-05-15",
            "MOATASIM FAROOG MOHAMMED NOOR outgoing IPS local transfer",
            -5000.0,
            [_counter(63, "102014 Other Receivable", 5000.0)],
            bank_partner_id=84,
            bank_partner_label="Petty Cash-Moatasim Faroog Mohammed Noor",
        ),
    ]
    transaction = {
        "date": "2026-06-01",
        "description": "MOATASIM FAROOG MOHAMMED NOOR outgoing IPS local transfer",
        "amount": -5000.0,
    }

    result = HistoricalSuggestionMatcher().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_account_id"] == 63
    assert result["suggested_partner_id"] == 84
    assert result["suggested_partner_label"] == "Petty Cash-Moatasim Faroog Mohammed Noor"
    assert result["resolution_mode"] == "partner_aware_top_k_reranker"


def test_v3_partner_signal_reranks_specific_counterparty_over_generic_payables_history():
    historical = [
        _history_entry(
            1,
            "2026-04-01",
            "MOATASIM FAROOG MOHAMMED NOOR outgoing IPS local transfer",
            -5000.0,
            [_counter(63, "102014 Other Receivable", 5000.0)],
            bank_partner_id=84,
            bank_partner_label="Petty Cash-Moatasim",
        ),
        _history_entry(
            2,
            "2026-04-10",
            "MOATASIM FAROOG MOHAMMED NOOR outgoing IPS local transfer",
            -5000.0,
            [_counter(63, "102014 Other Receivable", 5000.0)],
            bank_partner_id=84,
            bank_partner_label="Petty Cash-Moatasim",
        ),
    ]
    for move_id in range(3, 8):
        historical.append(
            _history_entry(
                move_id,
                f"2026-04-{10 + move_id:02d}",
                "OUTGOING IPS local transfer supplier payment",
                -5000.0,
                [_counter(102, "201002 Payables", 5000.0, partner_id=900, partner_name="Generic Supplier")],
            )
        )

    transaction = {
        "date": "2026-06-01",
        "description": "MOATASIM FAROOG MOHAMMED NOOR OUTGOING IPS local transfer",
        "amount": -5000.0,
    }
    result = HistoricalSuggestionMatcher().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_partner_id"] == 84
    assert result["suggested_account_id"] == 63
    assert result["alternatives"][0]["account_id"] == 63
    assert result["confidence_breakdown"]["partner_confidence"] > 0.5


def test_v3_infers_vat_from_repeated_posted_pattern_even_when_bank_text_omits_vat_wording():
    historical = []
    for move_id in range(1, 6):
        historical.append(
            _history_entry(
                move_id,
                f"2026-04-{move_id:02d}",
                "ACME CLOUD monthly subscription payment",
                -115.0,
                [
                    _counter(168, "400045 Subscriptions", 100.0, partner_id=55, partner_name="ACME CLOUD"),
                    _counter(90, "104041 VAT Input", 15.0, partner_id=55, partner_name="ACME CLOUD"),
                ],
                bank_partner_id=55,
                bank_partner_label="ACME CLOUD",
            )
        )

    transaction = {
        "date": "2026-05-01",
        "description": "ACME CLOUD monthly subscription payment",
        "amount": -115.0,
    }
    result = HistoricalSuggestionMatcher().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_account_id"] == 168
    assert result["predicted_vat_present"] is True
    assert result["vat_inference"]["method"] == "historical_vat_propensity_v2"
    assert result["vat_inference"]["historical_positive"] >= 2
    assert result["vat_inference"]["propensity"] >= 0.9


def test_v3_never_uses_future_posted_history_for_an_older_transaction():
    historical = [
        _history_entry(
            1,
            "2026-05-20",
            "ALPHA OFFICE RENT payment",
            -1000.0,
            [_counter(139, "400016 Office Rent", 1000.0, partner_id=11, partner_name="ALPHA")],
        ),
        _history_entry(
            2,
            "2026-06-10",
            "ALPHA OFFICE RENT payment",
            -1000.0,
            [_counter(999, "999999 Future Wrong Account", 1000.0, partner_id=11, partner_name="ALPHA")],
        ),
    ]
    transaction = {
        "date": "2026-06-01",
        "description": "ALPHA OFFICE RENT payment",
        "amount": -1000.0,
    }

    result = HistoricalSuggestionMatcher().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_account_id"] == 139
    assert all(item["account_id"] != 999 for item in result["alternatives"])


def _evaluation_history(count: int = 90):
    start = date(2026, 1, 1)
    rows = []
    for index in range(1, count + 1):
        occurred_on = (start + timedelta(days=index - 1)).isoformat()
        kind = index % 3
        if kind == 0:
            rows.append(
                _history_entry(
                    index,
                    occurred_on,
                    "ACME CLOUD monthly subscription payment",
                    -115.0,
                    [
                        _counter(168, "400045 Subscriptions", 100.0, analytic_id=2),
                        _counter(90, "104041 VAT Input", 15.0),
                    ],
                    bank_partner_id=55,
                    bank_partner_label="ACME CLOUD",
                )
            )
        elif kind == 1:
            rows.append(
                _history_entry(
                    index,
                    occurred_on,
                    "STC internet monthly bill",
                    -1150.0,
                    [_counter(143, "400020 Telephone And Internet", 1150.0, analytic_id=2)],
                    bank_partner_id=7,
                    bank_partner_label="stc السعودية",
                )
            )
        else:
            rows.append(
                _history_entry(
                    index,
                    occurred_on,
                    "MOL iqama government payment",
                    -650.0,
                    [_counter(133, "400010 Iqama Fees", 650.0, analytic_id=2)],
                    bank_partner_id=9,
                    bank_partner_label="MOL",
                )
            )
    return rows


def test_v2_untouched_evaluator_measures_historical_vat_partner_reranker_with_98pct_gate_target():
    service = BankReconciliationEvaluationServiceV2(
        db=None,
        context=SuggestionBatchContext(
            organization_id=1,
            company_id=1,
            bank_journal_id=10,
            bank_account_id=208,
        ),
    )

    report = service.evaluate_historical(_evaluation_history())

    assert report["status"] == "success"
    assert report["method"] == "strict_time_series_partner_vat_reranker_v2"
    assert report["calibration"]["target_precision"] == 0.98
    assert report["calibration"]["calibrated_from"] == "validation_only"
    assert report["leakage_checks"]["future_dated_history_filtered_by_matcher"] is True
    assert report["leakage_checks"]["vat_inference_uses_test_labels"] is False
    assert report["leakage_checks"]["partner_reranker_uses_test_labels"] is False

    metrics = report["untouched_test_metrics"]
    assert metrics["account"]["top1_accuracy"] >= 0.95
    assert metrics["partner"]["accuracy_on_labeled"] >= 0.95
    assert metrics["partner"]["coverage_on_labeled"] >= 0.95
    assert metrics["vat_detection"]["recall"] >= 0.90
    assert metrics["vat_detection"]["precision"] >= 0.90
    assert metrics["analytic"]["accuracy_on_labeled"] >= 0.95
    assert report["safe_to_post"] is False
    assert report["erp_mutation"] is False
