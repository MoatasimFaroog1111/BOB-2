from app.services.bank_reconciliation_features import detect_monetary_components
from app.services.bank_reconciliation_historical import HistoricalSuggestionMatcher
from app.services.bank_reconciliation_semantic import combine_advisors


def _counter(account_id, label, balance, *, partner_id=None, partner_name=""):
    return {
        "account_id": [account_id, label],
        "partner_id": [partner_id, partner_name] if partner_id else False,
        "balance": balance,
        "debit": max(balance, 0),
        "credit": abs(min(balance, 0)),
        "name": "counterpart",
        "ref": "",
        "move_id": [1, "BNK/2026/0001"],
    }


def test_fee_vat_components_parse_explicit_bank_fee_split():
    transaction = {
        "description": (
            "INSTANT PAYMENT FEE 00000000000001.00 SAR "
            "VAT AMOUNT 00000000000000.15 SAR VAT% 15%"
        ),
        "amount": -1.15,
    }

    components = detect_monetary_components(transaction)

    assert components["gross_amount"] == 1.15
    assert components["fee_amount"] == 1.0
    assert components["vat_amount"] == 0.15
    assert components["vat_rate"] == 15.0
    assert components["components_reconcile_to_total"] is True


def test_fee_vat_components_fall_back_to_inclusive_15_percent_when_statement_omits_decimal():
    transaction = {
        "description": "FEE 00000000000001.00 SAR VAT AMOUNT 000015 SAR VAT% 15%",
        "amount": -1.15,
    }

    components = detect_monetary_components(transaction)

    assert components["fee_amount"] == 1.0
    assert components["vat_amount"] == 0.15
    assert components["components_reconcile_to_total"] is True


def test_historical_matcher_uses_consensus_instead_of_one_nearest_row():
    transaction = {
        "description": "REF 123 MOATASIM FAROOG MOHAMMED NOOR personal transfer",
        "amount": -20000.0,
        "row_number": 2,
    }
    historical = [
        {
            "move_id": 1,
            "move_name": "BNK/2026/0001",
            "date": "2026-08-01",
            "bank_text": "MOATASIM FAROOG MOHAMMED NOOR personal transfer",
            "bank_amount": -20000.0,
            "counterparts": [
                _counter(
                    102014,
                    "102014 Petty Cash",
                    20000.0,
                    partner_id=7,
                    partner_name="Petty Cash-Moatasim",
                )
            ],
        },
        {
            "move_id": 2,
            "move_name": "BNK/2026/0002",
            "date": "2026-08-02",
            "bank_text": "MOATASIM FAROOG MOHAMMED NOOR personal transfer",
            "bank_amount": -20000.0,
            "counterparts": [
                _counter(
                    102014,
                    "102014 Petty Cash",
                    20000.0,
                    partner_id=7,
                    partner_name="Petty Cash-Moatasim",
                )
            ],
        },
        {
            "move_id": 3,
            "move_name": "BNK/2026/0003",
            "date": "2026-08-03",
            "bank_text": "advertising prepayment campaign",
            "bank_amount": -20000.0,
            "counterparts": [
                _counter(104033, "104033 PrePaid Advertisement Expenses", 20000.0)
            ],
        },
    ]

    result = HistoricalSuggestionMatcher().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_account_id"] == 102014
    assert result["suggested_partner_id"] == 7
    assert result["source"] == "odoo_historical_consensus"
    assert result["historical_support_count"] >= 2
    assert result["confidence_breakdown"]["historical_consensus"] > 0.5


def test_historical_matcher_prefers_primary_bank_fee_account_over_vat_split_line():
    transaction = {
        "description": "INSTANT PAYMENT FEE 1.00 SAR VAT AMOUNT 0.15 SAR VAT% 15%",
        "amount": -1.15,
    }
    historical = [
        {
            "move_id": 11,
            "move_name": "BNK/2026/0011",
            "date": "2026-08-19",
            "bank_text": "INSTANT PAYMENT FEE 1.00 SAR VAT AMOUNT 0.15 SAR VAT% 15%",
            "bank_amount": -1.15,
            "counterparts": [
                _counter(400051, "400051 Other Bank Charges", 1.00),
                _counter(104041, "104041 VAT Input", 0.15),
            ],
        }
    ]

    result = HistoricalSuggestionMatcher().suggest(transaction, historical)

    assert result is not None
    assert result["suggested_account_id"] == 400051
    assert result["alternatives"][0]["account_id"] == 400051
    assert result["confidence_breakdown"]["historical_consensus"] > 0.8


def test_ensemble_agreement_boosts_confidence_and_fills_partner():
    historical = {
        "suggested_account_id": 400020,
        "suggested_account_label": "400020 Telephone And Internet",
        "confidence": 0.84,
        "source": "odoo_historical_consensus",
        "needs_review": True,
    }
    semantic = {
        "suggested_account_id": 400020,
        "suggested_account_label": "400020 Telephone And Internet",
        "suggested_partner_id": 7,
        "suggested_partner_label": "stc السعودية",
        "confidence": 0.82,
        "source": "accounting_intelligence_memory",
        "needs_review": True,
    }

    result = combine_advisors(historical, semantic)

    assert result is not None
    assert result["suggested_account_id"] == 400020
    assert result["suggested_partner_id"] == 7
    assert result["advisor_agreement"] is True
    assert result["confidence"] > 0.84
    assert result["source"] == "historical_semantic_consensus"


def test_ensemble_disagreement_always_requires_accountant_review():
    historical = {
        "suggested_account_id": 400051,
        "confidence": 0.88,
        "source": "odoo_historical_consensus",
        "needs_review": True,
    }
    semantic = {
        "suggested_account_id": 104033,
        "confidence": 0.86,
        "source": "accounting_intelligence_memory",
        "needs_review": True,
    }

    result = combine_advisors(historical, semantic)

    assert result is not None
    assert result["suggested_account_id"] == 400051
    assert result["advisor_agreement"] is False
    assert result["advisor_conflict"]["semantic_account_id"] == 104033
    assert result["needs_review"] is True
