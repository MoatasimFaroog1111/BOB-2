from __future__ import annotations

from app.services.daily_bank_entry_builder import BankJournalContext, DailyBankEntryBuilder


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
        "confidence": 0.95,
        "source": "odoo_bank_reconciliation_rule",
        "bank_rule_id": 77,
        "bank_rule_name": "Fees",
        "reason": "Matched Odoo rule Fees",
        "needs_review": False,
    }


def test_groups_all_transactions_for_each_calendar_day_into_one_entry():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    transactions = [
        {"date": "2026-08-10", "description": "INSTANT PAYMENT FEE", "amount": "-1.00", "row_number": 1},
        {"date": "2026-08-10", "description": "SECOND FEE", "amount": "-2.00", "row_number": 2},
        {"date": "2026-08-11", "description": "THIRD FEE", "amount": "-3.00", "row_number": 3},
    ]

    entries = builder.build(transactions, rules=[{"id": 77}], journal=JOURNAL, account_catalog=ACCOUNTS)

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
        rules=[{"id": 77}],
        journal=JOURNAL,
        account_catalog=ACCOUNTS,
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


def test_inflow_debits_bank_and_credits_rule_account():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "INCOMING FEE", "amount": "25.00", "row_number": 5}],
        rules=[{"id": 77}],
        journal=JOURNAL,
        account_catalog=ACCOUNTS,
    )[0]

    bank_line, counterpart = entry["lines"]
    assert bank_line["debit"] == "25.00"
    assert bank_line["credit"] == "0.00"
    assert counterpart["debit"] == "0.00"
    assert counterpart["credit"] == "25.00"


def test_unmatched_transaction_stays_balanced_but_never_invents_account():
    builder = DailyBankEntryBuilder(rule_matcher=rule_matcher)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "UNKNOWN PAYMENT", "amount": "-100.00", "row_number": 6}],
        rules=[{"id": 77}],
        journal=JOURNAL,
        account_catalog=ACCOUNTS,
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

    entry = builder.build([txn, dict(txn)], rules=[{"id": 77}], journal=JOURNAL, account_catalog=ACCOUNTS)[0]

    assert entry["duplicate_count"] == 1
    assert entry["ready_for_review"] is False
    assert entry["ready_for_posting"] is False
