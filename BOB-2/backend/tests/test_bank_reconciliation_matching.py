import pytest

from app.services.bank_reconciliation_matching import (
    BankStatementLine,
    OdooBankLedgerLine,
    parse_bank_statement_text,
    reconcile_bank_to_odoo,
)


def test_parse_bank_statement_text_extracts_required_fields():
    text = "Date,Value Date,Description,Debit,Credit,Balance,Reference,Counterparty\n2026-01-02,2026-01-03,Vendor payment,100.00,,900.00,REF123,ABC Trading"
    lines = parse_bank_statement_text(text)
    assert len(lines) == 1
    line = lines[0]
    assert line.transaction_date == "2026-01-02"
    assert line.value_date == "2026-01-03"
    assert line.description == "Vendor payment"
    assert line.debit == 100.0
    assert line.credit == 0.0
    assert line.balance == 900.0
    assert line.reference == "REF123"
    assert line.counterparty == "ABC Trading"


def test_reconcile_exact_strong_possible_unmatched_missing_and_mismatch():
    bank_lines = [
        BankStatementLine(line_id="B1", transaction_date="2026-01-02", description="Vendor ABC payment REF123", debit=100, credit=0, reference="REF123", row_number=2),
        BankStatementLine(line_id="B2", transaction_date="2026-01-05", description="Riyad Bank fee", debit=10, credit=0, reference="FEE1", row_number=3),
        BankStatementLine(line_id="B3", transaction_date="2026-01-08", description="Customer XYZ receipt", debit=0, credit=250, reference="INV9", row_number=4),
        BankStatementLine(line_id="B4", transaction_date="2026-01-10", description="Unrecorded transfer", debit=50, credit=0, reference="NEW", row_number=5),
    ]
    odoo_lines = [
        OdooBankLedgerLine(line_id="O1", move_date="2026-01-02", journal_entry_number="BNK/1", label="Vendor ABC payment", partner="ABC Trading", debit=0, credit=100, balance=-100, amount=-100, payment_reference="REF123", move_id=1, account_id=10, journal_id=20, reconciliation_status="open"),
        OdooBankLedgerLine(line_id="O2", move_date="2026-01-06", journal_entry_number="BNK/2", label="Riyad bank charge", partner="Riyad Bank", debit=0, credit=12, balance=-12, amount=-12, payment_reference="FEE1", move_id=2, account_id=10, journal_id=20, reconciliation_status="open"),
        OdooBankLedgerLine(line_id="O3", move_date="2026-01-09", journal_entry_number="BNK/3", label="Customer XYZ receipt", partner="XYZ", debit=250, credit=0, balance=250, amount=250, payment_reference="INV9", move_id=3, account_id=10, journal_id=20, reconciliation_status="open"),
        OdooBankLedgerLine(line_id="O4", move_date="2026-01-11", journal_entry_number="BNK/4", label="Missing in bank", partner="Other", debit=25, credit=0, balance=25, amount=25, payment_reference="MISS", move_id=4, account_id=10, journal_id=20, reconciliation_status="open"),
    ]

    report = reconcile_bank_to_odoo(bank_lines, odoo_lines, tolerance_days=3)

    assert report.summary.exact_matches_count == 1
    assert report.summary.strong_matches_count == 1
    assert report.summary.amount_mismatch_count == 1
    assert report.summary.unmatched_bank_lines_count == 1
    assert report.summary.missing_in_bank_statement_count == 1
    assert report.matched_lines[0].confidence_score == 98
    assert report.amount_mismatches[0].amount_difference == 2.0
    assert report.unmatched_bank_lines[0].suggested_action == "import to Odoo"
    assert report.missing_in_bank_statement[0].suggested_action == "check posting date"


def test_invalid_bank_statement_text_raises_clear_error():
    with pytest.raises(ValueError, match="date and description/reference"):
        parse_bank_statement_text("foo,bar\n1,2")
