"""Comprehensive bank reconciliation and document AI tests.

Required tests (per spec):
 1. Bank statement CSV parsing
 2. Bank statement XLSX parsing
 3. Arabic bank statement row extraction
 4. English bank statement row extraction
 5. Empty file upload handling
 6. Unsupported file type handling
 7. Rule-based reconciliation exact match
 8. Rule-based reconciliation date-window match
 9. Odoo unavailable / no active Odoo connection response
10. Vector DB smart match fallback (ChromaDB unavailable)
11. Document AI invoice classification
12. Document AI receipt classification
13. Document AI ZATCA-like invoice extraction
14. Journal suggestion creation must remain draft
"""

import io
import csv
import os
import tempfile
from unittest.mock import patch

import pytest

from app.erp.bank_reconciliation import (
    Transaction,
    _extract_transactions_from_rows,
    _run_matching,
    parse_csv_file,
    parse_file,
    SUPPORTED_BANK_STATEMENT_EXTENSIONS,
)
from app.erp.document_ai import GuardianDocumentAI


# ── Helpers ──────────────────────────────────────────────


def _write_csv(rows: list[list[str]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def _make_txn(date: str, desc: str, amt: float, row: int = 1) -> Transaction:
    return Transaction(date=date, description=desc, amount=amt, row_number=row)


# ── 1. Bank statement CSV parsing ────────────────────────


class TestCSVParsing:
    def test_csv_basic_parsing(self, tmp_path):
        p = tmp_path / "stmt.csv"
        _write_csv(
            [
                ["Date", "Description", "Amount"],
                ["2026-01-05", "ATM Withdrawal", "-500.00"],
                ["2026-01-06", "Salary", "8000.00"],
            ],
            str(p),
        )
        txns = parse_csv_file(str(p))
        assert len(txns) == 2
        assert txns[0].amount == -500.0
        assert txns[1].amount == 8000.0

    def test_csv_debit_credit_columns(self, tmp_path):
        p = tmp_path / "stmt.csv"
        _write_csv(
            [
                ["Date", "Description", "Debit", "Credit"],
                ["2026-01-05", "ATM Withdrawal", "150.00", ""],
                ["2026-01-06", "Deposit", "", "3000.00"],
            ],
            str(p),
        )
        txns = parse_csv_file(str(p))
        assert len(txns) == 2
        assert txns[0].amount == -150.0
        assert txns[1].amount == 3000.0


# ── 2. Bank statement XLSX parsing ───────────────────────


class TestXLSXParsing:
    def test_xlsx_parsing(self, tmp_path):
        import openpyxl

        p = tmp_path / "stmt.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Date", "Description", "Amount"])
        ws.append(["2026-02-01", "POS Purchase", -250.0])
        ws.append(["2026-02-02", "Transfer In", 5000.0])
        wb.save(str(p))

        from app.erp.bank_reconciliation import parse_xlsx_file

        txns = parse_xlsx_file(str(p))
        assert len(txns) == 2
        assert txns[0].amount == -250.0
        assert txns[1].amount == 5000.0


# ── 3. Arabic bank statement row extraction ──────────────


class TestArabicExtraction:
    def test_arabic_headers(self):
        rows = [
            ["تاريخ", "البيان", "مدين", "دائن"],
            ["2026-01-10", "سحب نقدي", "200.00", ""],
            ["2026-01-11", "إيداع نقدي", "", "5000.00"],
        ]
        txns = _extract_transactions_from_rows(rows, has_header=True)
        assert len(txns) == 2
        assert txns[0].amount == -200.0
        assert txns[1].amount == 5000.0

    def test_arabic_preamble_skipped(self):
        rows = [
            ["كشف حساب بنك الراجحي", "", "", ""],
            ["الفترة من 2026-01-01 إلى 2026-01-31", "", "", ""],
            ["تاريخ", "الوصف", "مدين", "دائن"],
            ["2026-01-05", "رسوم بنكية", "50.00", ""],
        ]
        txns = _extract_transactions_from_rows(rows, has_header=True)
        assert len(txns) == 1
        assert txns[0].description == "رسوم بنكية"


# ── 4. English bank statement row extraction ─────────────


class TestEnglishExtraction:
    def test_english_headers(self):
        rows = [
            ["Date", "Description", "Debit", "Credit"],
            ["2026-03-01", "Wire Transfer", "", "10000.00"],
            ["2026-03-02", "Check Payment", "4500.00", ""],
        ]
        txns = _extract_transactions_from_rows(rows, has_header=True)
        assert len(txns) == 2
        assert txns[0].amount == 10000.0
        assert txns[1].amount == -4500.0


# ── 5. Empty file upload handling ────────────────────────


class TestEmptyFile:
    def test_empty_csv_returns_empty(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("")
        txns = parse_csv_file(str(p))
        assert txns == []

    def test_header_only_csv_returns_empty(self, tmp_path):
        p = tmp_path / "header_only.csv"
        _write_csv([["Date", "Description", "Amount"]], str(p))
        txns = parse_csv_file(str(p))
        assert txns == []

    def test_empty_upload_via_api(self, client, auth_headers):
        empty = io.BytesIO(b"")
        res = client.post(
            "/api/v1/erp/bank-statement-parse",
            files={"statement": ("empty.csv", empty, "text/csv")},
            headers=auth_headers,
        )
        assert res.status_code in (400, 422)


# ── 6. Unsupported file type handling ────────────────────


class TestUnsupportedFile:
    def test_unsupported_extension_raises(self, tmp_path):
        p = tmp_path / "data.exe"
        p.write_text("bad data")
        with pytest.raises(ValueError, match="Unsupported"):
            parse_file(str(p))

    def test_supported_extensions_defined(self):
        assert ".csv" in SUPPORTED_BANK_STATEMENT_EXTENSIONS
        assert ".xlsx" in SUPPORTED_BANK_STATEMENT_EXTENSIONS
        assert ".pdf" in SUPPORTED_BANK_STATEMENT_EXTENSIONS


# ── 7. Rule-based reconciliation exact match ─────────────


class TestExactMatch:
    def test_exact_amount_and_date_match(self):
        stmt = [_make_txn("2026-01-05", "ATM", -500.0, 1)]
        ledger = [_make_txn("2026-01-05", "ATM Withdrawal", -500.0, 1)]
        result = _run_matching(stmt, ledger)
        assert len(result.matched) == 1
        assert result.statement_only == []
        assert result.ledger_only == []

    def test_no_match_different_amount(self):
        stmt = [_make_txn("2026-01-05", "ATM", -500.0, 1)]
        ledger = [_make_txn("2026-01-05", "ATM", -501.0, 1)]
        with patch("app.erp.bank_reconciliation._vector_smart_match", return_value=[]):
            with patch("app.erp.bank_reconciliation._llm_smart_match", return_value=[]):
                result = _run_matching(stmt, ledger)
        assert len(result.matched) == 0
        assert len(result.statement_only) == 1
        assert len(result.ledger_only) == 1


# ── 8. Rule-based reconciliation date-window match ───────


class TestDateWindowMatch:
    def test_same_amount_different_date_matched_by_date_window(self):
        """_run_matching has a date-window pass that matches same-amount within a few days."""
        stmt = [_make_txn("2026-01-05", "Salary", 5000.0, 1)]
        ledger = [_make_txn("2026-01-07", "Salary Transfer", 5000.0, 1)]
        result = _run_matching(stmt, ledger)
        assert len(result.matched) == 1
        assert result.difference == 0.0

    def test_exact_match_takes_priority(self):
        stmt = [_make_txn("2026-01-05", "Fee", -100.0, 1)]
        ledger = [
            _make_txn("2026-01-05", "Fee", -100.0, 1),
            _make_txn("2026-01-06", "Fee", -100.0, 2),
        ]
        result = _run_matching(stmt, ledger)
        assert len(result.matched) == 1
        assert len(result.ledger_only) == 1


# ── 9. Odoo unavailable / no active Odoo connection ─────


class TestOdooUnavailable:
    def test_bank_reconciliation_no_erp_connection(self, client, tmp_path, auth_headers):
        p = tmp_path / "stmt.csv"
        _write_csv(
            [["Date", "Description", "Amount"], ["2026-01-05", "ATM", "-500"]],
            str(p),
        )
        with open(str(p), "rb") as f:
            res = client.post(
                "/api/v1/erp/bank-reconciliation",
                files={"statement": ("stmt.csv", f, "text/csv")},
                headers=auth_headers,
            )
        assert res.status_code == 400
        body = res.json()
        assert "detail" in body

    def test_parse_only_works_without_erp(self, client, tmp_path, auth_headers):
        p = tmp_path / "stmt.csv"
        _write_csv(
            [["Date", "Description", "Amount"], ["2026-01-05", "Salary", "5000"]],
            str(p),
        )
        with open(str(p), "rb") as f:
            res = client.post(
                "/api/v1/erp/bank-statement-parse",
                files={"statement": ("stmt.csv", f, "text/csv")},
                headers=auth_headers,
            )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["statement_count"] == 1


# ── 10. Vector DB smart match fallback ───────────────────


class TestVectorDBFallback:
    def test_smart_match_does_not_crash_without_chromadb(self):
        """Reconciliation must work even if vector DB / embeddings are unavailable."""
        stmt = [_make_txn("2026-01-05", "Bank charges", -50.0, 1)]
        ledger = [_make_txn("2026-01-06", "Service fees", -50.0, 1)]

        with patch("app.erp.bank_reconciliation._vector_smart_match", return_value=[]):
            result = _run_matching(stmt, ledger)
        assert result is not None
        assert result.statement_count == 1
        assert result.ledger_count == 1


# ── 11. Document AI invoice classification ───────────────


class TestDocAIInvoice:
    def test_classify_english_invoice(self):
        ai = GuardianDocumentAI()
        text = "Invoice Number INV-2026-001\nTotal Amount 5,000.00 SAR\nVAT 750.00"
        cls = ai.detect_document_class(text)
        assert cls == "invoice"

    def test_classify_arabic_invoice(self):
        ai = GuardianDocumentAI()
        text = "فاتورة رقم 12345\nالمبلغ الإجمالي 10,000.00 ر.س"
        cls = ai.detect_document_class(text)
        assert cls == "invoice"

    def test_extract_invoice_fields(self):
        ai = GuardianDocumentAI()
        text = "Invoice Number INV-001\nInvoice Date 15/06/2026\nSubtotal 4,000.00\nVAT Tax 600.00\nTotal Amount 4,600.00 SAR"
        fields = ai.extract_invoice_fields(text)
        assert fields["invoice_number"] == "INV-001"
        assert fields["taxable_amount"] == 4000.0
        assert fields["vat_amount"] == 600.0
        assert fields["total_amount"] is not None
        assert fields["total_amount"] >= 4000.0


# ── 12. Document AI receipt classification ───────────────


class TestDocAIReceipt:
    def test_classify_bank_receipt(self):
        ai = GuardianDocumentAI()
        text = "Riyad Bank\nAccount Transaction Details Receipt\nProcessing Date 01-06-2026"
        cls = ai.detect_document_class(text)
        assert cls == "receipt"

    def test_classify_sadad_receipt(self):
        ai = GuardianDocumentAI()
        text = "سداد\nBILLER ID: 050\nAmount 500.00 SAR"
        cls = ai.detect_document_class(text)
        assert cls == "sadad_receipt"

    def test_extract_receipt_amount(self):
        ai = GuardianDocumentAI()
        text = "Riyad Bank\nProcessing Date\n01-06-2026\n500.00 SAR\nREF ABC12345678"
        fields = ai.extract_receipt_fields(text)
        assert fields["amount"] == 500.0
        assert fields["transaction_ref"] == "ABC12345678"


# ── 13. Document AI ZATCA-like invoice extraction ────────


class TestDocAIZATCA:
    def test_classify_zatca(self):
        ai = GuardianDocumentAI()
        text = "فاتورة ضريبية\nهيئة الزكاة والضريبة والجمارك\nVAT 300040012345678\nTotal 1,150.00"
        cls = ai.detect_document_class(text)
        assert cls == "zatca_invoice"

    def test_extract_zatca_vat_number(self):
        ai = GuardianDocumentAI()
        text = "Tax Invoice\nZATCA\nTax ID Number 300040012345678\nSubtotal 1,000.00\nVAT Tax 150.00\nTotal 1,150.00 SAR"
        fields = ai.extract_invoice_fields(text)
        assert fields["vat_number"] == "300040012345678"
        assert fields["total_amount"] is not None
        assert fields["total_amount"] >= 1000.0

    def test_zatca_warnings_for_missing_fields(self):
        ai = GuardianDocumentAI()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("فاتورة ضريبية\nZATCA\nTotal 500.00")
            f.flush()
            try:
                result = ai.analyze_document(f.name)
                assert result["safe_to_post"] is False
                assert "vat_number_not_detected" in result["warnings"]
            finally:
                os.unlink(f.name)


# ── 14. Journal suggestion must remain draft ─────────────


class TestJournalDraft:
    def test_analyze_document_safe_to_post_false(self):
        ai = GuardianDocumentAI()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Invoice Number INV-TEST\nTotal Amount 2,500.00 SAR\nVAT 375.00")
            f.flush()
            try:
                result = ai.analyze_document(f.name)
                assert result["safe_to_post"] is False
                assert result["status"] == "analyzed"
                assert "next_step" in result
            finally:
                os.unlink(f.name)

    def test_receipt_safe_to_post_false(self):
        ai = GuardianDocumentAI()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Riyad Bank\nAccount Transaction Details Receipt\n500.00 SAR")
            f.flush()
            try:
                result = ai.analyze_document(f.name)
                assert result["safe_to_post"] is False
            finally:
                os.unlink(f.name)
