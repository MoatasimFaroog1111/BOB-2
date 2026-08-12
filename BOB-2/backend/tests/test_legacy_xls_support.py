from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.erp.spreadsheet_text_extractor import SpreadsheetTextExtractor
from app.security.file_validation import (
    FileValidationError,
    LEGACY_XLS_MAGIC,
    detect_file_type,
    validate_file_content,
    validate_file_extension,
)


class _FakeCell:
    def __init__(self, value, ctype: int = 1):
        self.value = value
        self.ctype = ctype


class _FakeSheet:
    name = "Transactions"

    def __init__(self):
        self._rows = [
            [_FakeCell("Date"), _FakeCell("Description"), _FakeCell("Amount")],
            [_FakeCell("2026-08-12"), _FakeCell("Bank charge"), _FakeCell(12.5)],
        ]
        self.nrows = len(self._rows)
        self.ncols = len(self._rows[0])

    def cell(self, row_index: int, col_index: int):
        return self._rows[row_index][col_index]


class _FakeWorkbook:
    nsheets = 1
    datemode = 0

    def __init__(self):
        self.sheet = _FakeSheet()
        self.unloaded: list[int] = []
        self.released = False

    def sheet_by_index(self, index: int):
        assert index == 0
        return self.sheet

    def unload_sheet(self, index: int) -> None:
        self.unloaded.append(index)

    def release_resources(self) -> None:
        self.released = True


def _install_fake_xlrd(monkeypatch) -> _FakeWorkbook:
    workbook = _FakeWorkbook()
    module = SimpleNamespace(
        XL_CELL_DATE=3,
        open_workbook=lambda *args, **kwargs: workbook,
        xldate_as_datetime=lambda value, datemode: value,
    )
    monkeypatch.setitem(sys.modules, "xlrd", module)
    return workbook


def test_xls_extension_is_enabled_when_xlsx_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_UPLOAD_EXTENSIONS", ".pdf,.xlsx")

    assert validate_file_extension("bank-statement.xls") is True


def test_legacy_xls_magic_is_detected():
    assert detect_file_type(LEGACY_XLS_MAGIC + b"legacy-workbook", ".xls") == ".xls"


def test_legacy_xls_content_is_validated_with_bounded_reader(monkeypatch):
    workbook = _install_fake_xlrd(monkeypatch)

    assert validate_file_content(LEGACY_XLS_MAGIC + b"legacy-workbook", ".xls") is True
    assert workbook.unloaded == [0]
    assert workbook.released is True


def test_macro_enabled_legacy_xls_is_rejected():
    content = LEGACY_XLS_MAGIC + b"padding" + "_VBA_PROJECT_CUR".encode("utf-16le")

    with pytest.raises(FileValidationError, match="Macro-enabled legacy spreadsheets"):
        validate_file_content(content, ".xls")


def test_spreadsheet_text_extractor_reads_xls_as_cells(monkeypatch, tmp_path):
    workbook = _install_fake_xlrd(monkeypatch)
    file_path = tmp_path / "transactions.xls"
    file_path.write_bytes(LEGACY_XLS_MAGIC + b"legacy-workbook")

    text = SpreadsheetTextExtractor().extract(file_path)

    assert "[Sheet: Transactions]" in text
    assert "Date\tDescription\tAmount" in text
    assert "2026-08-12\tBank charge\t12.5" in text
    assert workbook.unloaded == [0]
    assert workbook.released is True
