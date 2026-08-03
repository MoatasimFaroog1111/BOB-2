from decimal import Decimal
from pathlib import Path

import pdfplumber
import pypdf
import pypdfium2

from app.erp.bank_reconciliation import Transaction, parse_pdf_file
from app.erp.document_ai import GuardianDocumentAI


class _TextPage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(self, text: str = "", *, encrypted: bool = False):
        self.is_encrypted = encrypted
        self.pages = [_TextPage(text)]


def test_replacement_pdf_text_extraction_uses_pypdf(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    expected = "Invoice Number INV-42\nTotal Amount 1,150.00 SAR"
    monkeypatch.setattr(pypdf, "PdfReader", lambda *_args, **_kwargs: _Reader(expected))

    assert GuardianDocumentAI().extract_text(str(pdf_path)) == expected


def test_encrypted_pdf_is_rejected_without_ocr(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "encrypted.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *_args, **_kwargs: _Reader(encrypted=True),
    )
    ai = GuardianDocumentAI()
    monkeypatch.setattr(
        ai,
        "_ocr_file",
        lambda _path: (_ for _ in ()).throw(AssertionError("OCR must not run")),
    )

    assert ai.extract_text(str(pdf_path)) == "OCR_ERROR: encrypted PDF is not supported"


def test_empty_pdf_text_falls_back_to_rendered_page_ocr(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(pypdf, "PdfReader", lambda *_args, **_kwargs: _Reader(""))

    closed = {"bitmap": False, "page": False, "document": False}

    class FakeBitmap:
        def to_pil(self):
            return object()

        def close(self):
            closed["bitmap"] = True

    class FakePage:
        def render(self, *, scale):
            assert scale == 150 / 72
            return FakeBitmap()

        def close(self):
            closed["page"] = True

    class FakeDocument:
        def __len__(self):
            return 1

        def __getitem__(self, index):
            assert index == 0
            return FakePage()

        def close(self):
            closed["document"] = True

    monkeypatch.setattr(pypdfium2, "PdfDocument", lambda _path: FakeDocument())
    ai = GuardianDocumentAI()
    monkeypatch.setattr(ai, "_ocr_image", lambda _image: "OCR invoice text")

    assert ai.extract_text(str(pdf_path)) == "OCR invoice text"
    assert closed == {"bitmap": True, "page": True, "document": True}


def test_pdf_bank_statement_parser_maps_positioned_words(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    class FakePage:
        def extract_words(self, **_kwargs):
            return [
                {"x0": 20, "x1": 100, "top": 200, "text": "1,500.00"},
                {"x0": 170, "x1": 220, "top": 200, "text": "500.00"},
                {"x0": 380, "x1": 500, "top": 200, "text": "Deposit"},
                {"x0": 545, "x1": 590, "top": 200, "text": "6/15"},
            ]

    class FakeDocument:
        pages = [FakePage()]

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    document = FakeDocument()
    monkeypatch.setattr(pdfplumber, "open", lambda _path: document)

    transactions = parse_pdf_file(str(pdf_path))

    assert len(transactions) == 1
    transaction = transactions[0]
    assert isinstance(transaction, Transaction)
    assert transaction.description == "Deposit"
    assert transaction.amount == Decimal("500.00")
    assert transaction.credit == Decimal("500.00")
    assert transaction.debit == Decimal("0.00")
    assert transaction.balance == Decimal("1500.00")
    assert transaction.date == "2024-06-15"
    assert document.closed is True
