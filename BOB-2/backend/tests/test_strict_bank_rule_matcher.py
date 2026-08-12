from app.erp.strict_bank_rule_matcher import match_by_odoo_bank_rule_strict


def rule(pattern: str, *, operator: str = "contains", account_id: int = 51):
    return {
        "id": 7,
        "name": "Fees",
        "match_label": operator,
        "match_label_param": pattern,
        "match_note": False,
        "match_note_param": "",
        "match_amount_min": False,
        "match_amount_max": False,
        "match_transaction_type": False,
        "lines": [{"account_id": [account_id, "Other Bank Charges"]}],
    }


def test_explicit_contains_rule_matches_without_fuzzy_guessing():
    result = match_by_odoo_bank_rule_strict(
        {"description": "OUTGOING INSTANT PAYMENT FEES REF 123", "amount": -1.0, "row_number": 2},
        [rule("INSTANT PAYMENT FEES")],
    )

    assert result is not None
    assert result["suggested_account_id"] == 51
    assert result["bank_rule_name"] == "Fees"
    assert result["source_priority"] == "bank_rule_strict"


def test_configured_regex_rule_matches_exactly():
    result = match_by_odoo_bank_rule_strict(
        {"description": "OUTGOING INSTANT PAYMENT 9988", "amount": -10.0},
        [rule(r"OUTGOING\s+INSTANT\s+PAYMENT", operator="match_regex")],
    )

    assert result is not None
    assert result["confidence"] == 1.0


def test_unrelated_description_does_not_match_rule_by_similarity():
    result = match_by_odoo_bank_rule_strict(
        {"description": "PAYROLL TRANSFER", "amount": -5000.0},
        [rule("INSTANT PAYMENT FEES")],
    )

    assert result is None


def test_not_contains_operator_is_honored():
    result = match_by_odoo_bank_rule_strict(
        {"description": "REGULAR BANK FEE", "amount": -25.0},
        [rule("REVERSAL", operator="not_contains")],
    )

    assert result is not None


def test_unknown_label_operator_is_fail_closed():
    result = match_by_odoo_bank_rule_strict(
        {"description": "INSTANT PAYMENT FEES", "amount": -1.0},
        [rule("INSTANT PAYMENT FEES", operator="custom_unknown")],
    )

    assert result is None


def test_catch_all_rule_without_observable_condition_is_fail_closed():
    generic = rule("")
    result = match_by_odoo_bank_rule_strict(
        {"description": "ANY PAYMENT", "amount": -100.0},
        [generic],
    )

    assert result is None
