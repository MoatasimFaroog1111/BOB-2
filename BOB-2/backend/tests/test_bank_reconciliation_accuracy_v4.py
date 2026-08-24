from __future__ import annotations

from datetime import date, timedelta

from app.services.bank_reconciliation_accuracy_v4 import (
    HistoricalSuggestionMatcherV4,
    PartnerIdentityResolverV4,
    identity_keys,
)
from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_evaluation_v3 import BankReconciliationEvaluationServiceV3


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


def test_v4_identity_keys_extract_iban_and_long_account_without_short_references():
    keys = identity_keys("IPS REF 12345 beneficiary SA43 2000 0003 3021 2229 9940 account 4485099000004460")

    assert "iban:SA4320000003302122299940" in keys
    assert "acct:4485099000004460" in keys
    assert all("12345" not in key for key in keys)


def test_v4_prefers_accounting_counterpart_partner_over_misleading_bank_line_partner():
    historical = [
        _history_entry(
            1,
            "2026-04-01",
            "ACME INDUSTRIAL SUPPLY invoice payment",
            -4600.0,
            [_counter(151, "400030 Materials", 4600.0, partner_id=55, partner_name="ACME INDUSTRIAL SUPPLY")],
            bank_partner_id=900,
            bank_partner_label="BANK TRANSFER CLEARING",
        ),
        _history_entry(
            2,
            "2026-04-18",
            "ACME INDUSTRIAL SUPPLY invoice payment",
            -4700.0,
            [_counter(151, "400030 Materials", 4700.0, partner_id=55, partner_name="ACME INDUSTRIAL SUPPLY")],
            bank_partner_id=900,
            bank_partner_label="BANK TRANSFER CLEARING",
        ),
    ]
    transaction = {
        "date": "2026-05-01",
        "description": "ACME INDUSTRIAL SUPPLY invoice payment",
        "amount": -4650.0,
    }

    resolved = PartnerIdentityResolverV4().resolve(transaction, historical)

    assert resolved["partner_id"] == 55
    assert resolved["partner_label"] == "ACME INDUSTRIAL SUPPLY"
    assert resolved["ambiguous"] is False
    assert resolved["support"] >= 2


def test_v4_exact_iban_identity_recovers_partner_across_alias_text_changes():
    historical = [
        _history_entry(
            1,
            "2026-04-01",
            "OUTGOING IPS MOATASIM FAROOG SA4312345678901234567890",
            -5000.0,
            [_counter(63, "102014 Other Receivable", 5000.0, partner_id=84, partner_name="Petty Cash-Moatasim")],
        ),
        _history_entry(
            2,
            "2026-04-15",
            "LOCAL TRANSFER M FAROOG SA4312345678901234567890",
            -6000.0,
            [_counter(63, "102014 Other Receivable", 6000.0, partner_id=84, partner_name="Petty Cash-Moatasim")],
        ),
    ]
    transaction = {
        "date": "2026-05-10",
        "description": "IPS BENEFICIARY M.F. SA43 1234 5678 9012 3456 7890",
        "amount": -5500.0,
    }

    resolved = PartnerIdentityResolverV4().resolve(transaction, historical)

    assert resolved["partner_id"] == 84
    assert resolved["exact_support"] >= 1
    assert resolved["confidence"] >= 0.7


def test_v4_full_history_candidate_generation_beats_generic_same_amount_history():
    historical = [
        _history_entry(
            1,
            "2026-03-01",
            "MOATASIM FAROOG SA4312345678901234567890 PETTY CASH",
            -5000.0,
            [_counter(63, "102014 Other Receivable", 5000.0, partner_id=84, partner_name="Petty Cash-Moatasim")],
        ),
        _history_entry(
            2,
            "2026-03-10",
            "M FAROOG SA4312345678901234567890 CASH ADVANCE",
            -6000.0,
            [_counter(63, "102014 Other Receivable", 6000.0, partner_id=84, partner_name="Petty Cash-Moatasim")],
        ),
    ]
    for move_id in range(3, 25):
        historical.append(
            _history_entry(
                move_id,
                f"2026-04-{(move_id % 20) + 1:02d}",
                "OUTGOING IPS SUPPLIER PAYMENT",
                -5500.0,
                [_counter(102, "201002 Payables", 5500.0, partner_id=900 + move_id, partner_name=f"Supplier {move_id}")],
            )
        )

    transaction = {
        "date": "2026-05-20",
        "description": "IPS M FAROOG SA43 1234 5678 9012 3456 7890",
        "amount": -5500.0,
    }
    result = HistoricalSuggestionMatcherV4().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_partner_id"] == 84
    assert result["suggested_account_id"] == 63
    assert result["alternatives"][0]["account_id"] == 63
    assert result["candidate_generator"]["full_history_candidate_generation"] is True
    assert result["engine_version"] == "v4_identity_candidate_calibration"


def test_v4_preserves_v3_vat_and_analytic_outputs_while_reranking_identity():
    historical = []
    for move_id in range(1, 6):
        historical.append(
            _history_entry(
                move_id,
                f"2026-04-{move_id:02d}",
                "ACME CLOUD SA4311111111222233334444 subscription",
                -115.0,
                [
                    _counter(168, "400045 Subscriptions", 100.0, partner_id=55, partner_name="ACME CLOUD", analytic_id=2),
                    _counter(90, "104041 VAT Input", 15.0, partner_id=55, partner_name="ACME CLOUD"),
                ],
            )
        )
    transaction = {
        "date": "2026-05-01",
        "description": "ACME CLOUD SA43 1111 1111 2222 3333 4444 subscription",
        "amount": -115.0,
    }

    result = HistoricalSuggestionMatcherV4().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_account_id"] == 168
    assert result["suggested_partner_id"] == 55
    assert result["predicted_vat_present"] is True
    assert result["vat_inference"]["method"] == "historical_vat_propensity_v2"
    assert result["suggested_analytic_account_id"] == 2
    assert result["safe_to_post"] is False


def test_v4_filters_future_identity_and_account_evidence():
    historical = [
        _history_entry(
            1,
            "2026-05-01",
            "ALPHA RENT SA4312345678901234567000",
            -1000.0,
            [_counter(139, "400016 Office Rent", 1000.0, partner_id=11, partner_name="ALPHA")],
        ),
        _history_entry(
            2,
            "2026-06-15",
            "ALPHA RENT SA4312345678901234567000",
            -1000.0,
            [_counter(999, "Future Wrong", 1000.0, partner_id=99, partner_name="FUTURE")],
        ),
    ]
    transaction = {
        "date": "2026-06-01",
        "description": "ALPHA RENT SA43 1234 5678 9012 3456 7000",
        "amount": -1000.0,
    }

    result = HistoricalSuggestionMatcherV4().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_account_id"] == 139
    assert result["suggested_partner_id"] == 11
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
                    "ACME CLOUD SA4311111111222233334444 monthly subscription",
                    -115.0,
                    [
                        _counter(168, "400045 Subscriptions", 100.0, partner_id=55, partner_name="ACME CLOUD", analytic_id=2),
                        _counter(90, "104041 VAT Input", 15.0, partner_id=55, partner_name="ACME CLOUD"),
                    ],
                )
            )
        elif kind == 1:
            rows.append(
                _history_entry(
                    index,
                    occurred_on,
                    "STC SA4322222222333344445555 internet bill",
                    -1150.0,
                    [_counter(143, "400020 Telephone And Internet", 1150.0, partner_id=7, partner_name="stc السعودية", analytic_id=2)],
                )
            )
        else:
            rows.append(
                _history_entry(
                    index,
                    occurred_on,
                    "MOL SA4333333333444455556666 iqama government payment",
                    -650.0,
                    [_counter(133, "400010 Iqama Fees", 650.0, partner_id=9, partner_name="MOL", analytic_id=2)],
                )
            )
    return rows


def test_v4_untouched_evaluator_locks_99pct_account_gate_and_separate_partner_gate():
    service = BankReconciliationEvaluationServiceV3(
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
    assert report["method"] == "strict_time_series_identity_candidate_calibration_v3"
    assert report["engine_version"] == "v4_identity_candidate_calibration"
    assert report["calibration"]["target_precision"] == 0.99
    assert report["calibration"]["partner_gate"]["target_precision"] == 0.90
    assert report["calibration"]["calibrated_from"] == "validation_only"
    assert report["leakage_checks"]["future_dated_history_filtered_by_matcher"] is True
    assert report["leakage_checks"]["partner_identity_resolver_uses_test_labels"] is False
    assert report["leakage_checks"]["account_candidate_generator_uses_test_labels"] is False

    metrics = report["untouched_test_metrics"]
    assert metrics["account"]["top1_accuracy"] >= 0.95
    assert metrics["account"]["top3_accuracy"] >= 0.95
    assert metrics["partner"]["accuracy_on_labeled"] >= 0.90
    assert metrics["vat_detection"]["precision"] >= 0.90
    assert metrics["vat_detection"]["recall"] >= 0.90
    assert metrics["analytic"]["accuracy_on_labeled"] >= 0.95
    assert report["safe_to_post"] is False
    assert report["erp_mutation"] is False
