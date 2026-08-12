from __future__ import annotations

from app.erp.bank_rule_resolver import OdooBankRuleResolver
from app.erp.bank_rule_suggestions import fetch_odoo_bank_rules
from app.erp.strict_bank_rule_matcher import match_by_odoo_bank_rule_strict


def _rule(
    *,
    rule_id: int = 7,
    name: str = "Fees",
    match_label: str | bool = "contains",
    match_label_param: str = "INSTANT PAYMENT FEES",
    match_amount: str | bool = False,
    match_amount_min: float = 0.0,
    match_amount_max: float = 0.0,
    account_id: int = 51,
    account_name: str = "Other Bank Charges",
):
    return {
        "id": rule_id,
        "name": name,
        "sequence": 10,
        "match_label": match_label,
        "match_label_param": match_label_param,
        "match_amount": match_amount,
        "match_amount_min": match_amount_min,
        "match_amount_max": match_amount_max,
        "match_partner_ids": [],
        "lines": [
            {
                "id": 70,
                "model_id": [rule_id, name],
                "sequence": 10,
                "account_id": [account_id, account_name],
                "partner_id": False,
                "label": name,
                "amount_type": "percentage_st_line",
                "amount_string": "100",
            }
        ],
    }


def test_strict_contains_matches_any_odoo_label_transaction_details_or_note_text():
    txn = {
        "description": "INSTANT PAYMENT",
        "details": ["Reference 998877", "INSTANT PAYMENT FEES"],
        "amount": -1.15,
        "row_number": 216,
    }

    result = match_by_odoo_bank_rule_strict(txn, [_rule()])

    assert result is not None
    assert result["bank_rule_name"] == "Fees"
    assert result["suggested_account_id"] == 51
    assert result["confidence"] == 1.0
    assert result["resolution_mode"] == "strict_odoo_condition"


def test_odoo19_lower_amount_uses_max_parameter():
    rule = _rule(
        match_label=False,
        match_label_param="",
        match_amount="lower",
        match_amount_max=5.0,
    )

    assert match_by_odoo_bank_rule_strict({"description": "FEE", "amount": -4.99}, [rule]) is not None
    assert match_by_odoo_bank_rule_strict({"description": "FEE", "amount": -5.01}, [rule]) is None


def test_odoo19_greater_amount_uses_min_parameter():
    rule = _rule(
        match_label=False,
        match_label_param="",
        match_amount="greater",
        match_amount_min=1000.0,
    )

    assert match_by_odoo_bank_rule_strict({"description": "TRANSFER", "amount": -1000.0}, [rule]) is not None
    assert match_by_odoo_bank_rule_strict({"description": "TRANSFER", "amount": -999.99}, [rule]) is None


def test_manual_odoo_rule_can_be_suggested_but_is_never_posting_confidence():
    manual_fees = _rule(match_label=False, match_label_param="")
    resolver = OdooBankRuleResolver()

    result = resolver.resolve(
        {
            "description": "INSTANT PAYMENT FEES",
            "amount": -1.15,
            "row_number": 216,
        },
        [manual_fees],
    )

    assert result is not None
    assert result["bank_rule_name"] == "Fees"
    assert result["suggested_account_id"] == 51
    assert result["resolution_mode"] == "review_only_odoo_rule_suggestion"
    assert result["needs_review"] is True
    assert result["confidence"] <= 0.69


def test_unrelated_manual_rule_is_not_forced_when_similarity_is_too_weak():
    resolver = OdooBankRuleResolver()
    unrelated = _rule(name="Payroll", match_label=False, match_label_param="", account_name="Payroll Expense")

    result = resolver.resolve(
        {"description": "UNKNOWN UNIQUE CRYPTOGRAPHIC REFERENCE", "amount": -123.45},
        [unrelated],
    )

    assert result is None


class FakeERP:
    def __init__(self):
        self.calls = []

    def execute_kw(self, model, method, args, kwargs):
        self.calls.append((model, method, args, kwargs))
        if method == "fields_get":
            if model == "account.reconcile.model":
                fields = {
                    "id", "name", "sequence", "active", "company_id", "trigger", "can_be_proposed",
                    "match_journal_ids", "match_partner_ids", "match_amount", "match_amount_min",
                    "match_amount_max", "match_label", "match_label_param", "mapped_partner_id",
                }
            else:
                fields = {
                    "id", "model_id", "sequence", "account_id", "partner_id", "label",
                    "amount_type", "amount_string", "analytic_distribution", "tax_ids",
                }
            return {field: {"string": field, "type": "char"} for field in fields}
        if model == "account.reconcile.model":
            return [{
                "id": 7,
                "name": "Fees",
                "sequence": 10,
                "active": True,
                "company_id": [1, "Company"],
                "trigger": "manual",
                "can_be_proposed": True,
                "match_journal_ids": [10],
                "match_partner_ids": [],
                "match_amount": False,
                "match_amount_min": 0.0,
                "match_amount_max": 0.0,
                "match_label": "contains",
                "match_label_param": "INSTANT PAYMENT FEES",
                "mapped_partner_id": False,
            }]
        if model == "account.reconcile.model.line":
            return [{
                "id": 70,
                "model_id": [7, "Fees"],
                "sequence": 10,
                "account_id": [51, "Other Bank Charges"],
                "partner_id": False,
                "label": "Fees",
                "amount_type": "percentage_st_line",
                "amount_string": "100",
                "analytic_distribution": False,
                "tax_ids": [],
            }]
        raise AssertionError(model)


def test_loader_requests_odoo19_match_amount_and_label_fields_without_legacy_invalid_fields():
    erp = FakeERP()

    rules = fetch_odoo_bank_rules(erp, company_id=1, bank_journal_id=10)

    assert len(rules) == 1
    assert rules[0]["match_label"] == "contains"
    assert rules[0]["match_label_param"] == "INSTANT PAYMENT FEES"
    rule_read = next(call for call in erp.calls if call[0] == "account.reconcile.model" and call[1] == "search_read")
    selected = set(rule_read[3]["fields"])
    assert "match_amount" in selected
    assert "match_partner_ids" in selected
    assert "match_note" not in selected
    assert "match_transaction_type" not in selected
