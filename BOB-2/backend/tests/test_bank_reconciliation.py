from app.erp.bank_reconciliation import _extract_transactions_from_rows


def test_extract_transactions_detects_header_after_preamble():
    rows = [
        ["كشف حساب بنك الراجحي", "", "", ""],
        ["الفترة من 2026-01-01 إلى 2026-01-31", "", "", ""],
        ["Date", "Description", "Debit", "Credit"],
        ["2026-01-05", "ATM Withdrawal", "150.00", ""],
        ["2026-01-06", "Salary Transfer", "", "5000.00"],
    ]

    txns = _extract_transactions_from_rows(rows, has_header=True)

    assert len(txns) == 2
    assert txns[0].date == "2026-01-05"
    assert txns[0].amount == -150.0
    assert txns[1].date == "2026-01-06"
    assert txns[1].amount == 5000.0


def test_extract_transactions_supports_single_debit_column():
    rows = [
        ["Date", "Description", "Debit"],
        ["2026-01-05", "ATM Withdrawal", "150.00"],
        ["2026-01-06", "POS Purchase", "75.50"],
    ]

    txns = _extract_transactions_from_rows(rows, has_header=True)

    assert len(txns) == 2
    assert txns[0].amount == -150.0
    assert txns[1].amount == -75.5
