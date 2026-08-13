from __future__ import annotations

from app.services.daily_bank_entry_builder import BankJournalContext, DailyBankEntryBuilder
from app.services.daily_bank_review_bob_rules import BOBTaxAwareDailyBankEntryBuilder


JOURNAL = BankJournalContext(
    journal_id=10,
    journal_name="Riyadh Bank",
    journal_code="BNK1",
    bank_account_id=100,
    bank_account_code="101001",
    bank_account_name="Riyadh Bank",
    company_id=1,
)

ACCOUNTS = {
    100: {"id": 100, "code": "101001", "name": "Riyadh Bank"},
    200: {"id": 200, "code": "400051", "name": "Other Bank Charges"},
    300: {"id": 300, "code": "102020", "name": "VAT Input"},
}


def rule_matcher(txn, rules):
    if "FEE" not in txn["description"]:
        return None
    return {
        "suggested_account_id": 200,
        "suggested_account_label": "Other Bank Charges",
        "suggested_partner_id": None,
        "suggested_partner_label": "",
        "suggested_analytic_account_id": None,
        "suggested_analytic_account_label": "",
        "confidence": 1.0,
        "source": "bob_bank_rule",
        "source_priority": "bob_rule_priority",
        "resolution_mode": "strict_bob_rule",
        "bank_rule_id": 77,
        "bank_rule_version_id": 771,
        "bank_rule_version": 1,
        "bank_rule_fingerprint": "a" * 64,
        "bank_rule_name": "Fees",
        "reason": "Matched approved BOB rule Fees v1",
        "needs_review": False,
    }


def approved_rule(*, with_tax: bool = False):
    target = {"account_id": 200, "account_code": "400051", "account_name": "Other Bank Charges"}
    if with_tax:
        target.update({
            "tax_id": 15,
            "tax_name": "VAT 15% Purchases",
            "tax_rate": 15.0,
            "tax_amount_type": "percent",
            "tax_type_use": "purchase",
            "tax_account_id": 300,
            "tax_account_code": "102020",
            "tax_account_name": "VAT Input",
            "tax_amount_mode": "included_in_bank_amount",
        })
    return {"rule_id": 77, "target": target}


def test_groups_all_transactions_for_each_calendar_day_into_one_entry():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    transactions = [
        {"date": "2026-08-10", "description": "INSTANT PAYMENT FEE", "amount": "-1.00", "row_number": 1},
        {"date": "2026-08-10", "description": "SECOND FEE", "amount": "-2.00", "row_number": 2},
        {"date": "2026-08-11", "description": "THIRD FEE", "amount": "-3.00", "row_number": 3},
    ]
    entries = builder.build(transactions, rules=[approved_rule()], journal=JOURNAL, account_catalog=ACCOUNTS)
    assert [entry["entry_date"] for entry in entries] == ["2026-08-10", "2026-08-11"]
    assert entries[0]["transaction_count"] == 2
    assert entries[0]["line_count"] == 4
    assert entries[0]["total_debit"] == "3.00"
    assert entries[0]["total_credit"] == "3.00"
    assert entries[0]["ready_for_posting"] is True


def test_outflow_credits_bank_and_debits_bank_rule_account():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "BANK FEE", "amount": "-12.50", "row_number": 4}],
        rules=[approved_rule()], journal=JOURNAL, account_catalog=ACCOUNTS,
    )[0]
    bank_line, counterpart = entry["lines"]
    assert bank_line["role"] == "bank"
    assert bank_line["account_code"] == "101001"
    assert bank_line["debit"] == "0.00"
    assert bank_line["credit"] == "12.50"
    assert counterpart["role"] == "counterpart"
    assert counterpart["account_code"] == "400051"
    assert counterpart["debit"] == "12.50"
    assert counterpart["credit"] == "0.00"
    assert counterpart["bank_rule_name"] == "Fees"
    assert counterpart["bank_rule_version_id"] == 771
    assert counterpart["evidence_source"] == "bob_bank_rule"


def test_inflow_debits_bank_and_credits_rule_account():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "INCOMING FEE", "amount": "25.00", "row_number": 5}],
        rules=[approved_rule()], journal=JOURNAL, account_catalog=ACCOUNTS,
    )[0]
    bank_line, counterpart = entry["lines"]
    assert bank_line["debit"] == "25.00"
    assert bank_line["credit"] == "0.00"
    assert counterpart["debit"] == "0.00"
    assert counterpart["credit"] == "25.00"


def test_tax_rule_splits_gross_outflow_into_base_tax_and_bank():
    builder = BOBTaxAwareDailyBankEntryBuilder(rule_matcher=rule_matcher)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "BANK FEE VAT", "amount": "-115.00", "row_number": 7}],
        rules=[approved_rule(with_tax=True)], journal=JOURNAL, account_catalog=ACCOUNTS,
    )[0]
    bank_line, counterpart, tax_line = entry["lines"]
    assert bank_line["credit"] == "115.00"
    assert counterpart["debit"] == "100.00"
    assert counterpart["tax_amount"] == "15.00"
    assert tax_line["role"] == "tax"
    assert tax_line["account_code"] == "102020"
    assert tax_line["debit"] == "15.00"
    assert tax_line["credit"] == "0.00"
    assert entry["total_debit"] == "115.00"
    assert entry["total_credit"] == "115.00"
    assert entry["balanced"] is True


def test_tax_rule_splits_gross_inflow_without_double_counting_tax():
    builder = BOBTaxAwareDailyBankEntryBuilder(rule_matcher=rule_matcher)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "INCOMING FEE VAT", "amount": "230.00", "row_number": 8}],
        rules=[approved_rule(with_tax=True)], journal=JOURNAL, account_catalog=ACCOUNTS,
    )[0]
    bank_line, counterpart, tax_line = entry["lines"]
    assert bank_line["debit"] == "230.00"
    assert counterpart["credit"] == "200.00"
    assert tax_line["credit"] == "30.00"
    assert entry["total_debit"] == "230.00"
    assert entry["total_credit"] == "230.00"


def test_unmatched_transaction_stays_balanced_but_never_invents_account():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "UNKNOWN PAYMENT", "amount": "-100.00", "row_number": 6}],
        rules=[approved_rule()], journal=JOURNAL, account_catalog=ACCOUNTS,
    )[0]
    counterpart = entry["lines"][1]
    assert counterpart["account_id"] is None
    assert counterpart["account_code"] == ""
    assert entry["balanced"] is True
    assert entry["unresolved_count"] == 1
    assert entry["ready_for_review"] is True
    assert entry["ready_for_posting"] is False


def test_duplicate_source_transaction_is_flagged_and_not_posting_ready():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    txn = {"date": "2026-08-10", "description": "BANK FEE", "amount": "-1.00", "row_number": 9}
    entry = builder.build([txn, dict(txn)], rules=[approved_rule()], journal=JOURNAL, account_catalog=ACCOUNTS)[0]
    assert entry["duplicate_count"] == 1
    assert entry["ready_for_review"] is False
    assert entry["ready_for_posting"] is False
