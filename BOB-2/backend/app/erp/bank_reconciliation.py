"""Bank reconciliation engine."""
import csv
import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
DELIMITED_TEXT_EXTENSIONS = {".csv", ".tsv", ".txt"}
BANK_EXPORT_EXTENSIONS = {".ofx", ".qif", ".qfx", ".mt940", ".sta"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_BANK_STATEMENT_EXTENSIONS = SPREADSHEET_EXTENSIONS | DELIMITED_TEXT_EXTENSIONS | BANK_EXPORT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS


class Transaction(BaseModel):
    date: str
    description: str
    amount: float
    row_number: int
    ai_suggested_account: Optional[str] = None
    display_date: Optional[str] = None
    hijri_date: Optional[str] = None
    main_description: Optional[str] = None
    details: List[str] = Field(default_factory=list)
    debit: Optional[float] = None
    credit: Optional[float] = None
    balance: Optional[float] = None


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
    statement_total: float
    ledger_total: float
    difference: float
    statement_count: int
    ledger_count: int


def get_supported_statement_extensions() -> List[str]:
    return sorted(SUPPORTED_BANK_STATEMENT_EXTENSIONS)


def _to_western_digits(value: str) -> str:
    return str(value or "").translate(str.maketrans({
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٬": ",", "،": ",", "٫": ".",
    }))


def _parse_number(value: str) -> Optional[float]:
    raw = _to_western_digits(str(value or "")).strip()
    if not raw:
        return None
    if raw in {".", ".0", ".00"}:
        return 0.0
    negative = raw.startswith("(") and raw.endswith(")")
    text = re.sub(r"[^\d.,()\-]", "", raw).replace(",", "").replace(" ", "").replace("(", "").replace(")", "")
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        number = float(text)
        return -number if negative else number
    except ValueError:
        return None


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
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).strftime("%Y-%m-%d")
            first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            year = 2000 + year if year < 100 else year
            day, month = (second, first) if second > 12 else (first, second)
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def _detect_columns(headers: List[str]) -> dict:
    result = {"date": -1, "description": -1, "amount": -1, "debit": -1, "credit": -1, "balance": -1}
    keywords = {
        "date": ["date", "تاريخ"],
        "description": ["description", "الوصف", "البيان", "details", "وصف"],
        "amount": ["amount", "المبلغ", "مبلغ"],
        "debit": ["debit", "مدين", "withdrawal", "سحب", "خصم"],
        "credit": ["credit", "دائن", "deposit", "إيداع", "ايداع"],
        "balance": ["balance", "الرصيد"],
    }
    for idx, header in enumerate(headers):
        h = str(header or "").lower().strip()
        for key, words in keywords.items():
            if result[key] == -1 and any(word in h for word in words):
                result[key] = idx
    return result


def _find_header_row(rows: List[List[str]]) -> int:
    best_idx, best_score = 0, -1
    for idx, row in enumerate(rows[:30]):
        col = _detect_columns([str(cell).strip() for cell in row])
        score = (2 if col["date"] >= 0 else 0) + (2 if col["amount"] >= 0 or col["debit"] >= 0 or col["credit"] >= 0 else 0) + (1 if col["description"] >= 0 else 0)
        if score > best_score:
            best_idx, best_score = idx, score
        if score >= 4:
            return idx
    return best_idx


def _extract_transactions_from_rows(rows: List[List[str]], has_header: bool = True) -> List[Transaction]:
    if not rows or len(rows) < 2:
        return []
    header_idx = _find_header_row(rows) if has_header else -1
    headers = [str(cell).strip() for cell in rows[header_idx]] if has_header and header_idx >= 0 else []
    data_rows = rows[header_idx + 1:] if has_header else rows
    col = _detect_columns(headers) if headers else {"date": 0, "description": 1, "amount": 2, "debit": -1, "credit": -1, "balance": -1}
    if col["date"] < 0 or (col["amount"] < 0 and col["debit"] < 0 and col["credit"] < 0):
        return []
    txns: List[Transaction] = []
    for row_idx, row in enumerate(data_rows, start=1):
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        if not any(cells):
            continue
        date = _normalize_date(cells[col["date"]]) if 0 <= col["date"] < len(cells) else ""
        if not date:
            continue
        description = cells[col["description"]] if 0 <= col["description"] < len(cells) else ""
        debit = _parse_number(cells[col["debit"]]) if 0 <= col["debit"] < len(cells) else None
        credit = _parse_number(cells[col["credit"]]) if 0 <= col["credit"] < len(cells) else None
        amount = None
        if debit is not None or credit is not None:
            amount = (credit or 0.0) - (debit or 0.0)
        elif 0 <= col["amount"] < len(cells):
            amount = _parse_number(cells[col["amount"]])
        balance = _parse_number(cells[col["balance"]]) if 0 <= col["balance"] < len(cells) else None
        if amount is None or round(amount, 2) == 0.0:
            continue
        if not description:
            skip = {col["date"], col["amount"], col["debit"], col["credit"], col.get("balance", -1)}
            description = " ".join(cells[i] for i in range(len(cells)) if i not in skip and cells[i]).strip()
        if not description:
            continue
        txns.append(Transaction(date=date, display_date=date, description=description, main_description=description, amount=round(amount, 2), debit=debit or (abs(amount) if amount < 0 else 0.0), credit=credit or (amount if amount > 0 else 0.0), balance=balance, row_number=row_idx))
    return txns


def _read_text_file(file_path: str) -> str:
    for encoding in ["utf-8-sig", "utf-8", "cp1256", "cp1252", "iso-8859-1"]:
        try:
            with open(file_path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue
    return Path(file_path).read_text(encoding="utf-8", errors="ignore")


def _rows_from_text(text: str) -> List[List[str]]:
    rows = []
    for line in text.splitlines():
        line = _to_western_digits(line).strip()
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
    try:
        delimiter = csv.Sniffer().sniff(content[:4096]).delimiter
    except csv.Error:
        ext = Path(file_path).suffix.lower()
        delimiter = "\t" if ext == ".tsv" else "|" if "|" in content[:4096] else ";" if ";" in content[:4096] else ","
    return _extract_transactions_from_rows(list(csv.reader(io.StringIO(content), delimiter=delimiter)), has_header=True)


def parse_xlsx_file(file_path: str) -> List[Transaction]:
    import openpyxl
    workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = [[str(cell) if cell is not None else "" for cell in row] for row in worksheet.iter_rows(values_only=True)] if worksheet else []
    workbook.close()
    return _extract_transactions_from_rows(rows, has_header=True)


def parse_xls_file(file_path: str) -> List[Transaction]:
    import xlrd
    workbook = xlrd.open_workbook(file_path)
    worksheet = workbook.sheet_by_index(0)
    rows = []
    for row_idx in range(worksheet.nrows):
        row = []
        for col_idx in range(worksheet.ncols):
            cell_type = worksheet.cell_type(row_idx, col_idx)
            value = worksheet.cell_value(row_idx, col_idx)
            if cell_type == xlrd.XL_CELL_DATE:
                try:
                    row.append(xlrd.xldate_as_datetime(value, workbook.datemode).strftime("%Y-%m-%d"))
                except Exception:
                    row.append(str(value))
            else:
                row.append(str(value) if value != "" else "")
        rows.append(row)
    return _extract_transactions_from_rows(rows, has_header=True)


def parse_text_file(file_path: str) -> List[Transaction]:
    return _extract_transactions_from_rows(_rows_from_text(_read_text_file(file_path)), has_header=True)


def parse_ofx_file(file_path: str) -> List[Transaction]:
    text = _read_text_file(file_path)
    blocks = re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)", text, re.IGNORECASE | re.DOTALL)
    txns: List[Transaction] = []
    for idx, block in enumerate(blocks, start=1):
        def tag(name: str) -> str:
            match = re.search(rf"<{name}>([^\r\n<]+)", block, re.IGNORECASE)
            return match.group(1).strip() if match else ""
        date = _normalize_date(tag("DTPOSTED") or tag("DTUSER"))
        amount = _parse_number(tag("TRNAMT")) or 0.0
        description = " ".join(part for part in [tag("NAME"), tag("MEMO"), tag("CHECKNUM"), tag("FITID")] if part).strip()
        if date and amount and description:
            txns.append(Transaction(date=date, display_date=date, description=description, main_description=description, amount=round(amount, 2), debit=abs(amount) if amount < 0 else 0.0, credit=amount if amount > 0 else 0.0, row_number=idx))
    return txns


def parse_qif_file(file_path: str) -> List[Transaction]:
    text = _read_text_file(file_path)
    txns: List[Transaction] = []
    current: dict[str, str] = {}
    def flush(row_number: int) -> None:
        if not current:
            return
        amount = _parse_number(current.get("T", "")) or 0.0
        date = _normalize_date(current.get("D", ""))
        description = " ".join(part for part in [current.get("P", ""), current.get("M", "")] if part).strip()
        if date and amount and description:
            txns.append(Transaction(date=date, display_date=date, description=description, main_description=description, amount=round(amount, 2), debit=abs(amount) if amount < 0 else 0.0, credit=amount if amount > 0 else 0.0, row_number=row_number))
    for row, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue
        if line == "^":
            flush(row)
            current = {}
            continue
        key, value = line[:1], line[1:]
        if key in {"D", "T", "P", "M", "N"}:
            current[key] = value.strip()
    flush(len(text.splitlines()) + 1)
    return txns


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
    return parse_pdf_statement(file_path, Transaction, _ocr_image_to_text)


def parse_file(file_path: str) -> List[Transaction]:
    ext = Path(file_path).suffix.lower()
    logger.info("parse_file: starting ext=%s path=%s", ext, file_path)
    if ext in {".xlsx", ".xlsm"}:
        transactions = parse_xlsx_file(file_path)
    elif ext == ".xls":
        transactions = parse_xls_file(file_path)
    elif ext == ".csv":
        transactions = parse_csv_file(file_path)
    elif ext in {".tsv", ".txt", ".mt940", ".sta"}:
        transactions = parse_text_file(file_path)
    elif ext in {".ofx", ".qfx"}:
        transactions = parse_ofx_file(file_path)
    elif ext == ".qif":
        transactions = parse_qif_file(file_path)
    elif ext == ".pdf":
        transactions = parse_pdf_file(file_path)
    elif ext in IMAGE_EXTENSIONS:
        transactions = parse_image_file(file_path)
    else:
        supported = ", ".join(get_supported_statement_extensions())
        raise ValueError(f"Unsupported bank statement file format '{ext}'. Supported formats: {supported}")
    logger.info("parse_file: completed, extracted %d transactions", len(transactions))
    if not transactions:
        supported = ", ".join(get_supported_statement_extensions())
        raise ValueError(f"No real bank transactions were extracted from the uploaded document. Supported formats: {supported}.")
    return transactions


def transactions_from_odoo_move_lines(move_lines: list) -> List[Transaction]:
    transactions: List[Transaction] = []
    for idx, line in enumerate(move_lines):
        date = _normalize_date(str(line.get("date", "")))
        name = line.get("name") or ""
        ref = line.get("ref") or ""
        description = name if name else ref
        if name and ref and name != ref:
            description = f"{name} - {ref}"
        debit = float(line.get("debit", 0) or 0)
        credit = float(line.get("credit", 0) or 0)
        amount = round(debit - credit, 2)
        if amount == 0.0:
            continue
        transactions.append(Transaction(date=date, display_date=date, description=description, main_description=description, amount=amount, debit=abs(amount) if amount < 0 else 0.0, credit=amount if amount > 0 else 0.0, row_number=idx + 1))
    return transactions


# Maximum time (seconds) allowed for vector DB operations before falling back.
_VECTOR_DB_TIMEOUT_SECONDS = 30


def _vector_smart_match(
    statement_only: List[Transaction],
    ledger_only: List[Transaction],
    confidence_threshold: float = 0.6,
) -> List[SmartMatch]:
    """Use Vector DB (ChromaDB) to find semantically similar transaction pairs.

    Runs with a timeout to prevent hanging if embedding model download or
    ChromaDB initialization is slow (e.g. first run in production).
    """
    try:
        from app.services.vector_db import (
            index_bank_transactions,
            search_similar_transactions,
        )
    except Exception:
        logger.debug("Vector DB unavailable; skipping vector smart match.")
        return []

    def _run_vector_match() -> List[SmartMatch]:
        ledger_dicts = [
            {"date": t.date, "description": t.description, "amount": t.amount, "row_number": t.row_number}
            for t in ledger_only
        ]
        index_bank_transactions(ledger_dicts, source="ledger")

        results: List[SmartMatch] = []
        used_ledger_rows: set[int] = set()

        for s_txn in statement_only:
            query = f"{s_txn.date} {s_txn.description} {s_txn.amount}"
            hits = search_similar_transactions(
                query_text=query,
                source_filter="ledger",
                n_results=5,
                amount=s_txn.amount,
            )
            for hit in hits:
                meta = hit.get("metadata", {})
                ledger_row = int(meta.get("row_number", 0))
                if ledger_row in used_ledger_rows:
                    continue

                vector_score = hit.get("score", 0.0)
                amount_match = abs(s_txn.amount - float(meta.get("amount", 0))) < 0.01
                amount_close = abs(s_txn.amount - float(meta.get("amount", 0))) / max(abs(s_txn.amount), 1.0) < 0.05

                combined = vector_score
                if amount_match:
                    combined = min(0.99, vector_score * 0.5 + 0.5)
                elif amount_close:
                    combined = min(0.95, vector_score * 0.6 + 0.35)

                if combined < confidence_threshold:
                    continue

                matched_ledger = next(
                    (t for t in ledger_only if t.row_number == ledger_row),
                    None,
                )
                if matched_ledger is None:
                    continue

                used_ledger_rows.add(ledger_row)
                reason = f"Vector DB similarity={vector_score:.2f}"
                if amount_match:
                    reason += " (exact amount)"
                results.append(SmartMatch(
                    statement_txn=s_txn,
                    ledger_txn=matched_ledger,
                    confidence=round(combined, 2),
                    reason=reason,
                ))
                break

        return results

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_run_vector_match)
        return future.result(timeout=_VECTOR_DB_TIMEOUT_SECONDS)
    except FuturesTimeoutError:
        logger.warning("Vector DB smart match timed out after %ds; skipping.", _VECTOR_DB_TIMEOUT_SECONDS)
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
    """Original LLM-based smart matching as fallback."""
    if not statement_only or not ledger_only:
        return []
    stmt_subset = statement_only[:30]
    ledg_subset = ledger_only[:30]
    stmt_lines = "\n".join(f"S{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\"" for i, t in enumerate(stmt_subset))
    ledg_lines = "\n".join(f"L{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\"" for i, t in enumerate(ledg_subset))
    system_prompt = "Return likely bank reconciliation matches as JSON array only: [{\"s\":1,\"l\":1,\"confidence\":0.8,\"reason\":\"...\"}]."
    try:
        from app.services.llm_service import chat
        raw = chat(system_prompt, f"Bank Statement:\n{stmt_lines}\n\nOdoo Ledger:\n{ledg_lines}", temperature=0.0, timeout=60)
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
        used_s: set[int] = set()
        used_l: set[int] = set()
        for pair in pairs:
            try:
                s_idx = int(pair.get("s", 0)) - 1
                l_idx = int(pair.get("l", 0)) - 1
                confidence = float(pair.get("confidence", 0))
                reason = str(pair.get("reason", ""))
            except (TypeError, ValueError):
                continue
            if confidence < confidence_threshold or s_idx in used_s or l_idx in used_l:
                continue
            if 0 <= s_idx < len(stmt_subset) and 0 <= l_idx < len(ledg_subset):
                used_s.add(s_idx)
                used_l.add(l_idx)
                results.append(SmartMatch(statement_txn=stmt_subset[s_idx], ledger_txn=ledg_subset[l_idx], confidence=round(confidence, 2), reason=reason))
        return results
    except Exception:
        return []


def _smart_match(
    statement_only: List[Transaction],
    ledger_only: List[Transaction],
    confidence_threshold: float = 0.6,
) -> List[SmartMatch]:
    """Hybrid smart matching: Vector DB first, then LLM fallback for unmatched."""
    if not statement_only or not ledger_only:
        return []

    vector_matches = _vector_smart_match(statement_only, ledger_only, confidence_threshold)

    matched_stmt_rows = {m.statement_txn.row_number for m in vector_matches}
    matched_ledg_rows = {m.ledger_txn.row_number for m in vector_matches}
    remaining_stmt = [t for t in statement_only if t.row_number not in matched_stmt_rows]
    remaining_ledg = [t for t in ledger_only if t.row_number not in matched_ledg_rows]

    llm_matches = _llm_smart_match(remaining_stmt, remaining_ledg, confidence_threshold)

    return vector_matches + llm_matches


def _suggest_accounts(statement_only: List[Transaction]) -> List[Transaction]:
    return statement_only


def _run_matching(statement_txns: List[Transaction], ledger_txns: List[Transaction]) -> ReconciliationResult:
    ledger_matched = [False] * len(ledger_txns)
    statement_matched = [False] * len(statement_txns)
    matched_pairs: List[MatchedPair] = []
    for s_idx, s_txn in enumerate(statement_txns):
        for l_idx, l_txn in enumerate(ledger_txns):
            if statement_matched[s_idx] or ledger_matched[l_idx]:
                continue
            if abs(s_txn.amount - l_txn.amount) < 0.01 and s_txn.date == l_txn.date:
                statement_matched[s_idx] = True
                ledger_matched[l_idx] = True
                matched_pairs.append(MatchedPair(statement_txn=s_txn, ledger_txn=l_txn))
                break
    for s_idx, s_txn in enumerate(statement_txns):
        if statement_matched[s_idx]:
            continue
        for l_idx, l_txn in enumerate(ledger_txns):
            if ledger_matched[l_idx] or abs(s_txn.amount - l_txn.amount) >= 0.01:
                continue
            try:
                if abs((datetime.strptime(s_txn.date, "%Y-%m-%d") - datetime.strptime(l_txn.date, "%Y-%m-%d")).days) <= 7:
                    statement_matched[s_idx] = True
                    ledger_matched[l_idx] = True
                    matched_pairs.append(MatchedPair(statement_txn=s_txn, ledger_txn=l_txn))
                    break
            except (ValueError, TypeError):
                continue
    statement_only = [t for i, t in enumerate(statement_txns) if not statement_matched[i]]
    ledger_only = [t for i, t in enumerate(ledger_txns) if not ledger_matched[i]]
    smart_matches = _smart_match(statement_only, ledger_only)
    smart_stmt_rows = {m.statement_txn.row_number for m in smart_matches}
    smart_ledg_rows = {m.ledger_txn.row_number for m in smart_matches}
    statement_only = _suggest_accounts([t for t in statement_only if t.row_number not in smart_stmt_rows])
    ledger_only = [t for t in ledger_only if t.row_number not in smart_ledg_rows]
    statement_total = sum(t.amount for t in statement_txns)
    ledger_total = sum(t.amount for t in ledger_txns)
    return ReconciliationResult(
        statement_only=statement_only,
        ledger_only=ledger_only,
        matched=matched_pairs,
        smart_matched=smart_matches,
        statement_total=round(statement_total, 2),
        ledger_total=round(ledger_total, 2),
        difference=round(statement_total - ledger_total, 2),
        statement_count=len(statement_txns),
        ledger_count=len(ledger_txns),
    )


def reconcile(statement_path: str, ledger_path: str) -> ReconciliationResult:
    return _run_matching(parse_file(statement_path), parse_file(ledger_path))


def get_date_range(transactions: List[Transaction], buffer_days: int = 7) -> tuple:
    dates = [t.date for t in transactions if t.date and t.date >= "1900"]
    if not dates:
        return None, None
    start = datetime.strptime(min(dates), "%Y-%m-%d") - timedelta(days=buffer_days)
    end = datetime.strptime(max(dates), "%Y-%m-%d") + timedelta(days=buffer_days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def reconcile_with_odoo_data(statement_path: str, odoo_move_lines: list) -> ReconciliationResult:
    return _run_matching(parse_file(statement_path), transactions_from_odoo_move_lines(odoo_move_lines))
