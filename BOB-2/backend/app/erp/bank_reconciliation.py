"""Fixed-point bank reconciliation engine."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer

from app.core.money import MONEY_ZERO, Money, MoneyValidationError, money_sum, money_to_str, parse_money

logger = logging.getLogger(__name__)

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
DELIMITED_TEXT_EXTENSIONS = {".csv", ".tsv", ".txt"}
BANK_EXPORT_EXTENSIONS = {".ofx", ".qif", ".qfx", ".mt940", ".sta"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_BANK_STATEMENT_EXTENSIONS = (
    SPREADSHEET_EXTENSIONS
    | DELIMITED_TEXT_EXTENSIONS
    | BANK_EXPORT_EXTENSIONS
    | PDF_EXTENSIONS
    | IMAGE_EXTENSIONS
)


class Transaction(BaseModel):
    date: str
    description: str
    amount: Money
    row_number: int
    ai_suggested_account: Optional[str] = None
    display_date: Optional[str] = None
    hijri_date: Optional[str] = None
    main_description: Optional[str] = None
    details: List[str] = Field(default_factory=list)
    debit: Optional[Money] = None
    credit: Optional[Money] = None
    balance: Optional[Money] = None

    @field_serializer("amount", "debit", "credit", "balance", when_used="json")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return money_to_str(value) if value is not None else None


class MatchedPair(BaseModel):
    statement_txn: Transaction
    ledger_txn: Transaction


class SmartMatch(BaseModel):
    statement_txn: Transaction
    ledger_txn: Transaction
    confidence: float
    reason: str


class ReconciliationResult(BaseModel):
    statement_only: List[Transaction]
    ledger_only: List[Transaction]
    matched: List[MatchedPair]
    smart_matched: List[SmartMatch] = Field(default_factory=list)
    statement_total: Money
    ledger_total: Money
    difference: Money
    statement_count: int
    ledger_count: int

    @field_serializer("statement_total", "ledger_total", "difference", when_used="json")
    def serialize_total(self, value: Decimal) -> str:
        return money_to_str(value)


def get_supported_statement_extensions() -> List[str]:
    return sorted(SUPPORTED_BANK_STATEMENT_EXTENSIONS)


def _to_western_digits(value: str) -> str:
    return str(value or "").translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
                "۰": "0",
                "۱": "1",
                "۲": "2",
                "۳": "3",
                "۴": "4",
                "۵": "5",
                "۶": "6",
                "۷": "7",
                "۸": "8",
                "۹": "9",
                "٬": ",",
                "،": ",",
                "٫": ".",
            }
        )
    )


def _parse_number(value: str) -> Optional[Decimal]:
    raw = _to_western_digits(str(value or "")).strip()
    if not raw:
        return None
    if raw in {".", ".0", ".00"}:
        return MONEY_ZERO
    negative = raw.startswith("(") and raw.endswith(")")
    text = (
        re.sub(r"[^\d.,()\-]", "", raw)
        .replace(",", "")
        .replace(" ", "")
        .replace("(", "")
        .replace(")", "")
    )
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        amount = parse_money(text)
    except MoneyValidationError:
        return None
    return -amount if negative else amount


def _normalize_date(value: str) -> str:
    text = _to_western_digits(str(value or "")).strip()
    if not text:
        return ""
    patterns = [
        (r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", "ymd"),
        (r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", "dmy"),
        (r"\b(\d{4})(\d{2})(\d{2})\b", "ymd"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if kind == "ymd":
                return datetime(
                    int(match.group(1)), int(match.group(2)), int(match.group(3))
                ).strftime("%Y-%m-%d")
            first, second, year = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            year = 2000 + year if year < 100 else year
            day, month = (second, first) if second > 12 else (first, second)
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def _detect_columns(headers: List[str]) -> dict:
    result = {
        "date": -1,
        "description": -1,
        "amount": -1,
        "debit": -1,
        "credit": -1,
        "balance": -1,
    }
    keywords = {
        "date": ["date", "تاريخ"],
        "description": ["description", "الوصف", "البيان", "details", "وصف"],
        "amount": ["amount", "المبلغ", "مبلغ"],
        "debit": ["debit", "مدين", "withdrawal", "سحب", "خصم"],
        "credit": ["credit", "دائن", "deposit", "إيداع", "ايداع"],
        "balance": ["balance", "الرصيد"],
    }
    for idx, header in enumerate(headers):
        normalized = str(header or "").lower().strip()
        for key, words in keywords.items():
            if result[key] == -1 and any(word in normalized for word in words):
                result[key] = idx
    return result


def _find_header_row(rows: List[List[str]]) -> int:
    best_idx, best_score = 0, -1
    for idx, row in enumerate(rows[:30]):
        columns = _detect_columns([str(cell).strip() for cell in row])
        score = (
            (2 if columns["date"] >= 0 else 0)
            + (2 if columns["amount"] >= 0 or columns["debit"] >= 0 or columns["credit"] >= 0 else 0)
            + (1 if columns["description"] >= 0 else 0)
        )
        if score > best_score:
            best_idx, best_score = idx, score
        if score >= 4:
            return idx
    return best_idx


def _transaction_from_amounts(
    *,
    date: str,
    description: str,
    amount: Decimal,
    row_number: int,
    balance: Decimal | None = None,
    display_date: str | None = None,
    **extra,
) -> Transaction:
    normalized_amount = parse_money(amount)
    debit = abs(normalized_amount) if normalized_amount < MONEY_ZERO else MONEY_ZERO
    credit = normalized_amount if normalized_amount > MONEY_ZERO else MONEY_ZERO
    return Transaction(
        date=date,
        display_date=display_date or date,
        description=description,
        main_description=extra.pop("main_description", description),
        amount=normalized_amount,
        debit=debit,
        credit=credit,
        balance=balance,
        row_number=row_number,
        **extra,
    )


def _extract_transactions_from_rows(
    rows: List[List[str]], has_header: bool = True
) -> List[Transaction]:
    if not rows or len(rows) < 2:
        return []
    header_idx = _find_header_row(rows) if has_header else -1
    headers = (
        [str(cell).strip() for cell in rows[header_idx]]
        if has_header and header_idx >= 0
        else []
    )
    data_rows = rows[header_idx + 1 :] if has_header else rows
    columns = (
        _detect_columns(headers)
        if headers
        else {
            "date": 0,
            "description": 1,
            "amount": 2,
            "debit": -1,
            "credit": -1,
            "balance": -1,
        }
    )
    if columns["date"] < 0 or (
        columns["amount"] < 0 and columns["debit"] < 0 and columns["credit"] < 0
    ):
        return []

    transactions: List[Transaction] = []
    for row_idx, row in enumerate(data_rows, start=1):
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        if not any(cells):
            continue
        date = (
            _normalize_date(cells[columns["date"]])
            if 0 <= columns["date"] < len(cells)
            else ""
        )
        if not date:
            continue
        description = (
            cells[columns["description"]]
            if 0 <= columns["description"] < len(cells)
            else ""
        )
        debit = (
            _parse_number(cells[columns["debit"]])
            if 0 <= columns["debit"] < len(cells)
            else None
        )
        credit = (
            _parse_number(cells[columns["credit"]])
            if 0 <= columns["credit"] < len(cells)
            else None
        )
        if debit is not None or credit is not None:
            amount = (credit or MONEY_ZERO) - (debit or MONEY_ZERO)
        elif 0 <= columns["amount"] < len(cells):
            amount = _parse_number(cells[columns["amount"]])
        else:
            amount = None
        balance = (
            _parse_number(cells[columns["balance"]])
            if 0 <= columns["balance"] < len(cells)
            else None
        )
        if amount is None or amount == MONEY_ZERO:
            continue
        if not description:
            skip = {
                columns["date"],
                columns["amount"],
                columns["debit"],
                columns["credit"],
                columns.get("balance", -1),
            }
            description = " ".join(
                cells[index]
                for index in range(len(cells))
                if index not in skip and cells[index]
            ).strip()
        if not description:
            continue
        transactions.append(
            _transaction_from_amounts(
                date=date,
                description=description,
                amount=amount,
                balance=balance,
                row_number=row_idx,
            )
        )
    return transactions


def _read_text_file(file_path: str) -> str:
    for encoding in ["utf-8-sig", "utf-8", "cp1256", "cp1252", "iso-8859-1"]:
        try:
            with open(file_path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue
    return Path(file_path).read_text(encoding="utf-8", errors="ignore")


def _rows_from_text(text: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for raw_line in text.splitlines():
        line = _to_western_digits(raw_line).strip()
        if not line:
            continue
        if "\t" in line:
            cells = [cell.strip() for cell in line.split("\t")]
        elif "|" in line:
            cells = [cell.strip() for cell in line.split("|")]
        elif ";" in line:
            cells = [cell.strip() for cell in line.split(";")]
        elif "," in line and line.count(",") >= 2:
            cells = [cell.strip() for cell in next(csv.reader([line]))]
        else:
            cells = [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]
        rows.append(cells or [line])
    return rows


def parse_csv_file(file_path: str) -> List[Transaction]:
    content = _read_text_file(file_path)
    if not content.strip():
        return []
    try:
        delimiter = csv.Sniffer().sniff(content[:4096]).delimiter
    except csv.Error:
        extension = Path(file_path).suffix.lower()
        delimiter = (
            "\t"
            if extension == ".tsv"
            else "|"
            if "|" in content[:4096]
            else ";"
            if ";" in content[:4096]
            else ","
        )
    return _extract_transactions_from_rows(
        list(csv.reader(io.StringIO(content), delimiter=delimiter)), has_header=True
    )


def parse_xlsx_file(file_path: str) -> List[Transaction]:
    import openpyxl

    workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = (
        [[str(cell) if cell is not None else "" for cell in row] for row in worksheet.iter_rows(values_only=True)]
        if worksheet
        else []
    )
    workbook.close()
    return _extract_transactions_from_rows(rows, has_header=True)


def parse_xls_file(file_path: str) -> List[Transaction]:
    import xlrd

    workbook = xlrd.open_workbook(file_path)
    worksheet = workbook.sheet_by_index(0)
    rows: List[List[str]] = []
    for row_idx in range(worksheet.nrows):
        row: List[str] = []
        for col_idx in range(worksheet.ncols):
            cell_type = worksheet.cell_type(row_idx, col_idx)
            value = worksheet.cell_value(row_idx, col_idx)
            if cell_type == xlrd.XL_CELL_DATE:
                try:
                    row.append(
                        xlrd.xldate_as_datetime(value, workbook.datemode).strftime("%Y-%m-%d")
                    )
                except Exception:
                    row.append(str(value))
            else:
                row.append(str(value) if value != "" else "")
        rows.append(row)
    return _extract_transactions_from_rows(rows, has_header=True)


def parse_text_file(file_path: str) -> List[Transaction]:
    return _extract_transactions_from_rows(
        _rows_from_text(_read_text_file(file_path)), has_header=True
    )


def parse_ofx_file(file_path: str) -> List[Transaction]:
    text = _read_text_file(file_path)
    blocks = re.findall(
        r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    transactions: List[Transaction] = []
    for idx, block in enumerate(blocks, start=1):
        def tag(name: str) -> str:
            match = re.search(rf"<{name}>([^\r\n<]+)", block, re.IGNORECASE)
            return match.group(1).strip() if match else ""

        date = _normalize_date(tag("DTPOSTED") or tag("DTUSER"))
        amount = _parse_number(tag("TRNAMT")) or MONEY_ZERO
        description = " ".join(
            part
            for part in [tag("NAME"), tag("MEMO"), tag("CHECKNUM"), tag("FITID")]
            if part
        ).strip()
        if date and amount != MONEY_ZERO and description:
            transactions.append(
                _transaction_from_amounts(
                    date=date,
                    description=description,
                    amount=amount,
                    row_number=idx,
                )
            )
    return transactions


def parse_qif_file(file_path: str) -> List[Transaction]:
    text = _read_text_file(file_path)
    transactions: List[Transaction] = []
    current: dict[str, str] = {}

    def flush(row_number: int) -> None:
        if not current:
            return
        amount = _parse_number(current.get("T", "")) or MONEY_ZERO
        date = _normalize_date(current.get("D", ""))
        description = " ".join(
            part for part in [current.get("P", ""), current.get("M", "")] if part
        ).strip()
        if date and amount != MONEY_ZERO and description:
            transactions.append(
                _transaction_from_amounts(
                    date=date,
                    description=description,
                    amount=amount,
                    row_number=row_number,
                )
            )

    for row_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue
        if line == "^":
            flush(row_number)
            current = {}
            continue
        key, value = line[:1], line[1:]
        if key in {"D", "T", "P", "M", "N"}:
            current[key] = value.strip()
    flush(len(text.splitlines()) + 1)
    return transactions


def _ocr_image_to_text(image) -> str:
    import pytesseract

    try:
        return pytesseract.image_to_string(image, lang="ara+eng")
    except Exception:
        return pytesseract.image_to_string(image)


def parse_image_file(file_path: str) -> List[Transaction]:
    from PIL import Image, ImageOps

    with Image.open(file_path) as image:
        normalized = ImageOps.exif_transpose(image)
        if normalized.mode not in ("RGB", "L"):
            normalized = normalized.convert("RGB")
        text = _ocr_image_to_text(normalized)
    return _extract_transactions_from_rows(_rows_from_text(text), has_header=True)


def parse_pdf_file(file_path: str) -> List[Transaction]:
    from app.erp.pdf_statement_parser import parse_pdf_statement

    parsed = parse_pdf_statement(file_path, Transaction, _ocr_image_to_text)
    return [Transaction.model_validate(item) for item in parsed]


def parse_file(file_path: str) -> List[Transaction]:
    extension = Path(file_path).suffix.lower()
    logger.info("parse_file: starting ext=%s path=%s", extension, file_path)
    if extension in {".xlsx", ".xlsm"}:
        transactions = parse_xlsx_file(file_path)
    elif extension == ".xls":
        transactions = parse_xls_file(file_path)
    elif extension == ".csv":
        transactions = parse_csv_file(file_path)
    elif extension in {".tsv", ".txt", ".mt940", ".sta"}:
        transactions = parse_text_file(file_path)
    elif extension in {".ofx", ".qfx"}:
        transactions = parse_ofx_file(file_path)
    elif extension == ".qif":
        transactions = parse_qif_file(file_path)
    elif extension == ".pdf":
        transactions = parse_pdf_file(file_path)
    elif extension in IMAGE_EXTENSIONS:
        transactions = parse_image_file(file_path)
    else:
        supported = ", ".join(get_supported_statement_extensions())
        raise ValueError(
            f"Unsupported bank statement file format '{extension}'. Supported formats: {supported}"
        )
    logger.info("parse_file: completed, extracted %d transactions", len(transactions))
    if not transactions:
        supported = ", ".join(get_supported_statement_extensions())
        raise ValueError(
            "No real bank transactions were extracted from the uploaded document. "
            f"Supported formats: {supported}."
        )
    return transactions


def transactions_from_odoo_move_lines(move_lines: list) -> List[Transaction]:
    transactions: List[Transaction] = []
    for idx, line in enumerate(move_lines, start=1):
        date = _normalize_date(str(line.get("date", "")))
        name = line.get("name") or ""
        ref = line.get("ref") or ""
        description = name if name else ref
        if name and ref and name != ref:
            description = f"{name} - {ref}"
        try:
            debit = parse_money(line.get("debit", MONEY_ZERO), allow_negative=False)
            credit = parse_money(line.get("credit", MONEY_ZERO), allow_negative=False)
        except MoneyValidationError:
            logger.warning("Skipping malformed Odoo monetary line at index %d", idx)
            continue
        amount = debit - credit
        if amount == MONEY_ZERO:
            continue
        transactions.append(
            _transaction_from_amounts(
                date=date,
                description=description,
                amount=amount,
                row_number=idx,
            )
        )
    return transactions


_VECTOR_DB_TIMEOUT_SECONDS = 30


def _vector_smart_match(
    statement_only: List[Transaction],
    ledger_only: List[Transaction],
    confidence_threshold: float = 0.6,
) -> List[SmartMatch]:
    """Use semantic similarity only as a bounded review suggestion."""

    try:
        from app.services.vector_db import index_bank_transactions, search_similar_transactions
    except Exception:
        logger.debug("Vector DB unavailable; skipping vector smart match.")
        return []

    def run_vector_match() -> List[SmartMatch]:
        ledger_dicts = [
            {
                "date": txn.date,
                "description": txn.description,
                "amount": money_to_str(txn.amount),
                "row_number": txn.row_number,
            }
            for txn in ledger_only
        ]
        index_bank_transactions(ledger_dicts, source="ledger")
        results: List[SmartMatch] = []
        used_ledger_rows: set[int] = set()

        for statement_txn in statement_only:
            query = (
                f"{statement_txn.date} {statement_txn.description} "
                f"{money_to_str(statement_txn.amount)}"
            )
            hits = search_similar_transactions(
                query_text=query,
                source_filter="ledger",
                n_results=5,
                amount=float(money_to_str(statement_txn.amount)),
            )
            for hit in hits:
                metadata = hit.get("metadata", {})
                ledger_row = int(metadata.get("row_number", 0))
                if ledger_row in used_ledger_rows:
                    continue
                matched_ledger = next(
                    (txn for txn in ledger_only if txn.row_number == ledger_row), None
                )
                if matched_ledger is None:
                    continue
                try:
                    metadata_amount = parse_money(metadata.get("amount", MONEY_ZERO))
                except MoneyValidationError:
                    continue
                vector_score = float(hit.get("score", 0.0))
                amount_match = statement_txn.amount == metadata_amount
                denominator = max(abs(statement_txn.amount), Decimal("1.00"))
                amount_close = abs(statement_txn.amount - metadata_amount) / denominator < Decimal("0.05")
                combined = vector_score
                if amount_match:
                    combined = min(0.99, vector_score * 0.5 + 0.5)
                elif amount_close:
                    combined = min(0.95, vector_score * 0.6 + 0.35)
                if combined < confidence_threshold:
                    continue
                used_ledger_rows.add(ledger_row)
                reason = f"Vector DB similarity={vector_score:.2f}"
                if amount_match:
                    reason += " (exact amount)"
                results.append(
                    SmartMatch(
                        statement_txn=statement_txn,
                        ledger_txn=matched_ledger,
                        confidence=round(combined, 2),
                        reason=reason,
                    )
                )
                break
        return results

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(run_vector_match)
        return future.result(timeout=_VECTOR_DB_TIMEOUT_SECONDS)
    except FuturesTimeoutError:
        logger.warning(
            "Vector DB smart match timed out after %ds; skipping.",
            _VECTOR_DB_TIMEOUT_SECONDS,
        )
        return []
    except Exception as exc:
        logger.warning("Vector DB smart match failed: %s; skipping.", exc)
        return []
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _llm_smart_match(
    statement_only: List[Transaction],
    ledger_only: List[Transaction],
    confidence_threshold: float = 0.6,
) -> List[SmartMatch]:
    """Local-only LLM review fallback; never authoritative for balances."""

    if not statement_only or not ledger_only:
        return []
    statement_subset = statement_only[:30]
    ledger_subset = ledger_only[:30]
    statement_lines = "\n".join(
        f"S{i + 1}: date={txn.date} amount={money_to_str(txn.amount)} desc=\"{txn.description}\""
        for i, txn in enumerate(statement_subset)
    )
    ledger_lines = "\n".join(
        f"L{i + 1}: date={txn.date} amount={money_to_str(txn.amount)} desc=\"{txn.description}\""
        for i, txn in enumerate(ledger_subset)
    )
    system_prompt = (
        'Return likely bank reconciliation matches as JSON array only: '
        '[{"s":1,"l":1,"confidence":0.8,"reason":"..."}].'
    )
    try:
        from app.services.llm_service import chat

        raw = chat(
            system_prompt,
            f"Bank Statement:\n{statement_lines}\n\nOdoo Ledger:\n{ledger_lines}",
            temperature=0.0,
            timeout=60,
        )
        if not raw:
            return []
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        pairs = json.loads(text.strip())
        if not isinstance(pairs, list):
            return []
        results: List[SmartMatch] = []
        used_statement: set[int] = set()
        used_ledger: set[int] = set()
        for pair in pairs:
            try:
                statement_index = int(pair.get("s", 0)) - 1
                ledger_index = int(pair.get("l", 0)) - 1
                confidence = float(pair.get("confidence", 0))
                reason = str(pair.get("reason", ""))
            except (TypeError, ValueError):
                continue
            if (
                confidence < confidence_threshold
                or statement_index in used_statement
                or ledger_index in used_ledger
            ):
                continue
            if 0 <= statement_index < len(statement_subset) and 0 <= ledger_index < len(ledger_subset):
                used_statement.add(statement_index)
                used_ledger.add(ledger_index)
                results.append(
                    SmartMatch(
                        statement_txn=statement_subset[statement_index],
                        ledger_txn=ledger_subset[ledger_index],
                        confidence=round(confidence, 2),
                        reason=reason,
                    )
                )
        return results
    except Exception:
        return []


def _smart_match(
    statement_only: List[Transaction],
    ledger_only: List[Transaction],
    confidence_threshold: float = 0.6,
) -> List[SmartMatch]:
    if not statement_only or not ledger_only:
        return []
    vector_matches = _vector_smart_match(
        statement_only, ledger_only, confidence_threshold
    )
    matched_statement_rows = {match.statement_txn.row_number for match in vector_matches}
    matched_ledger_rows = {match.ledger_txn.row_number for match in vector_matches}
    remaining_statement = [
        txn for txn in statement_only if txn.row_number not in matched_statement_rows
    ]
    remaining_ledger = [
        txn for txn in ledger_only if txn.row_number not in matched_ledger_rows
    ]
    return vector_matches + _llm_smart_match(
        remaining_statement, remaining_ledger, confidence_threshold
    )


def _suggest_accounts(statement_only: List[Transaction]) -> List[Transaction]:
    return statement_only


def _run_matching(
    statement_txns: List[Transaction], ledger_txns: List[Transaction]
) -> ReconciliationResult:
    statement = [Transaction.model_validate(txn) for txn in statement_txns]
    ledger = [Transaction.model_validate(txn) for txn in ledger_txns]
    ledger_matched = [False] * len(ledger)
    statement_matched = [False] * len(statement)
    matched_pairs: List[MatchedPair] = []

    for statement_index, statement_txn in enumerate(statement):
        for ledger_index, ledger_txn in enumerate(ledger):
            if statement_matched[statement_index] or ledger_matched[ledger_index]:
                continue
            if statement_txn.amount == ledger_txn.amount and statement_txn.date == ledger_txn.date:
                statement_matched[statement_index] = True
                ledger_matched[ledger_index] = True
                matched_pairs.append(
                    MatchedPair(statement_txn=statement_txn, ledger_txn=ledger_txn)
                )
                break

    for statement_index, statement_txn in enumerate(statement):
        if statement_matched[statement_index]:
            continue
        for ledger_index, ledger_txn in enumerate(ledger):
            if ledger_matched[ledger_index] or statement_txn.amount != ledger_txn.amount:
                continue
            try:
                date_distance = abs(
                    (
                        datetime.strptime(statement_txn.date, "%Y-%m-%d")
                        - datetime.strptime(ledger_txn.date, "%Y-%m-%d")
                    ).days
                )
            except (ValueError, TypeError):
                continue
            if date_distance <= 7:
                statement_matched[statement_index] = True
                ledger_matched[ledger_index] = True
                matched_pairs.append(
                    MatchedPair(statement_txn=statement_txn, ledger_txn=ledger_txn)
                )
                break

    statement_only = [
        txn for index, txn in enumerate(statement) if not statement_matched[index]
    ]
    ledger_only = [txn for index, txn in enumerate(ledger) if not ledger_matched[index]]
    smart_matches = _smart_match(statement_only, ledger_only)
    smart_statement_rows = {match.statement_txn.row_number for match in smart_matches}
    smart_ledger_rows = {match.ledger_txn.row_number for match in smart_matches}
    statement_only = _suggest_accounts(
        [txn for txn in statement_only if txn.row_number not in smart_statement_rows]
    )
    ledger_only = [
        txn for txn in ledger_only if txn.row_number not in smart_ledger_rows
    ]

    statement_total = money_sum(txn.amount for txn in statement)
    ledger_total = money_sum(txn.amount for txn in ledger)
    return ReconciliationResult(
        statement_only=statement_only,
        ledger_only=ledger_only,
        matched=matched_pairs,
        smart_matched=smart_matches,
        statement_total=statement_total,
        ledger_total=ledger_total,
        difference=parse_money(statement_total - ledger_total),
        statement_count=len(statement),
        ledger_count=len(ledger),
    )


def reconcile(statement_path: str, ledger_path: str) -> ReconciliationResult:
    return _run_matching(parse_file(statement_path), parse_file(ledger_path))


def get_date_range(
    transactions: List[Transaction], buffer_days: int = 7
) -> tuple[str | None, str | None]:
    dates = [txn.date for txn in transactions if txn.date and txn.date >= "1900"]
    if not dates:
        return None, None
    start = datetime.strptime(min(dates), "%Y-%m-%d") - timedelta(days=buffer_days)
    end = datetime.strptime(max(dates), "%Y-%m-%d") + timedelta(days=buffer_days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def reconcile_with_odoo_data(
    statement_path: str, odoo_move_lines: list
) -> ReconciliationResult:
    return _run_matching(
        parse_file(statement_path), transactions_from_odoo_move_lines(odoo_move_lines)
    )
