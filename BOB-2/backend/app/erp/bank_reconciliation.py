"""
Bank reconciliation engine.

Parses bank statement and bank ledger files used by accountants, including
CSV/TSV/TXT, Excel (XLSX/XLS/XLSM), PDF, scanned images, OFX/QIF, and MT940-like
plain text exports, extracts transactions, and compares them to find
discrepancies.

Convention used throughout:
  - Deposits / money-in  → positive amount
  - Withdrawals / money-out → negative amount

This applies to BOTH bank statement parsing and Odoo move lines conversion
so that amounts can be compared directly.
"""
import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


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


def get_supported_statement_extensions() -> List[str]:
    """Return all supported bank statement upload extensions."""
    return sorted(SUPPORTED_BANK_STATEMENT_EXTENSIONS)


class Transaction(BaseModel):
    date: str
    description: str
    amount: float
    row_number: int
    ai_suggested_account: Optional[str] = None


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
    smart_matched: List[SmartMatch] = []
    statement_total: float
    ledger_total: float
    difference: float
    statement_count: int
    ledger_count: int


def _to_western_digits(value: str) -> str:
    """Convert Arabic/Persian digits and separators to parser-friendly text."""
    text = str(value or "")
    translation = str.maketrans({
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٬": ",", "،": ",", "٫": ".",
    })
    return text.translate(translation)


def _parse_number(value: str) -> Optional[float]:
    """Parse a number from a string, handling Arabic numerals, commas and brackets."""
    if value is None or not str(value).strip():
        return None

    text = _to_western_digits(str(value)).strip()
    is_parentheses_negative = text.startswith("(") and text.endswith(")")

    # Remove currency symbols and whitespace, but keep signs, decimals, commas and brackets.
    text = re.sub(r"[^\d\.\-,\(\)]", "", text)
    text = text.replace(",", "")
    text = text.replace("(", "").replace(")", "")

    if not text or text in ("-", ".", "-."):
        return None

    try:
        parsed = float(text)
        if is_parentheses_negative and parsed > 0:
            parsed = -parsed
        return parsed
    except ValueError:
        return None


def _normalize_date(date_str: str) -> str:
    """Normalize date string to YYYY-MM-DD format."""
    if not date_str or not str(date_str).strip():
        return ""

    text = _to_western_digits(str(date_str)).strip()

    months_map = {
        "january": "01", "february": "02", "march": "03", "april": "04", "may": "05", "june": "06",
        "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "sept": "09", "oct": "10", "nov": "11", "dec": "12",
        "يناير": "01", "فبراير": "02", "مارس": "03", "أبريل": "04", "ابريل": "04", "مايو": "05",
        "يونيو": "06", "يونيه": "06", "يوليو": "07", "يوليه": "07", "أغسطس": "08", "اغسطس": "08",
        "سبتمبر": "09", "أكتوبر": "10", "اكتوبر": "10", "نوفمبر": "11", "ديسمبر": "12",
    }

    lower = text.lower()
    for month_name, month_num in months_map.items():
        if month_name in lower:
            match_day_year = re.search(r"\b(\d{1,2})\b.*\b(\d{4})\b", text)
            if match_day_year:
                day = int(match_day_year.group(1))
                year = int(match_day_year.group(2))
                try:
                    return datetime(year, int(month_num), day).strftime("%Y-%m-%d")
                except ValueError:
                    pass

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"(\d{4})[-/\.](\d{1,2})[-/\.](\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # DD-MM-YYYY or DD/MM/YYYY
    m = re.search(r"(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{4})", text)
    if m:
        v1, v2, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if v2 > 12:
            day, month = v2, v1
        else:
            day, month = v1, v2
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Compact OFX date: YYYYMMDD...
    m = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return text


def _detect_columns(headers: List[str]) -> dict:
    """Auto-detect which columns contain date, description, amount, debit and credit."""
    date_keywords = [
        "date", "تاريخ", "التاريخ", "value date", "posting date", "book date",
        "transaction date", "effective date", "تاريخ العملية", "تاريخ القيد",
    ]
    desc_keywords = [
        "description", "الوصف", "البيان", "memo", "details", "تفاصيل",
        "narrative", "reference", "المرجع", "particulars", "remarks", "payee",
        "beneficiary", "اسم المستفيد", "وصف العملية",
    ]
    amount_keywords = [
        "amount", "المبلغ", "مبلغ", "transaction amount", "net amount",
        "withdrawal", "deposit", "paid out", "paid in",
    ]
    debit_keywords = [
        "debit", "مدين", "withdrawal", "سحب", "خصم", "paid out", "debit amount",
        "amount debit", "مدين / debit",
    ]
    credit_keywords = [
        "credit", "دائن", "deposit", "إيداع", "ايداع", "paid in", "credit amount",
        "amount credit", "دائن / credit",
    ]
    balance_keywords = ["balance", "الرصيد", "running balance", "available balance"]

    result = {"date": -1, "description": -1, "amount": -1, "debit": -1, "credit": -1, "balance": -1}

    for i, h in enumerate(headers):
        h_lower = str(h or "").lower().strip()
        if result["date"] == -1 and any(k in h_lower for k in date_keywords):
            result["date"] = i
        elif result["description"] == -1 and any(k in h_lower for k in desc_keywords):
            result["description"] = i
        elif result["debit"] == -1 and any(k in h_lower for k in debit_keywords):
            result["debit"] = i
        elif result["credit"] == -1 and any(k in h_lower for k in credit_keywords):
            result["credit"] = i
        elif result["balance"] == -1 and any(k in h_lower for k in balance_keywords):
            result["balance"] = i
        elif result["amount"] == -1 and any(k in h_lower for k in amount_keywords):
            result["amount"] = i

    return result


def _find_header_row_index(rows: List[List[str]], max_scan_rows: int = 20) -> int:
    """Find the most likely header row index in files that contain preamble lines."""
    scan_limit = min(len(rows), max_scan_rows)
    best_idx = 0
    best_score = -1

    for idx in range(scan_limit):
        row = rows[idx]
        headers = [str(c).strip() if c is not None else "" for c in row]
        if not any(headers):
            continue

        col_map = _detect_columns(headers)

        has_date = col_map["date"] >= 0
        has_amount_info = (
            col_map["amount"] >= 0 or
            col_map["debit"] >= 0 or
            col_map["credit"] >= 0
        )

        score = 0
        if has_date:
            score += 2
        if has_amount_info:
            score += 2
        if col_map["description"] >= 0:
            score += 1

        if score > best_score:
            best_score = score
            best_idx = idx

        if has_date and has_amount_info:
            return idx

    return best_idx


def _extract_transactions_from_rows(rows: List[List[str]], has_header: bool = True) -> List[Transaction]:
    """Extract transactions from parsed rows.

    Amount sign convention (matches Odoo and bank statement):
      deposit  (credit / money-in)  → positive
      withdrawal (debit / money-out) → negative
    When separate debit/credit columns exist: amount = credit - debit
    When a single signed amount column exists: value is used as-is.
    """
    if not rows or len(rows) < 2:
        return []

    if has_header:
        header_idx = _find_header_row_index(rows)
        headers = [str(c).strip() if c is not None else "" for c in rows[header_idx]]
        data_rows = rows[header_idx + 1:]
    else:
        headers = []
        data_rows = rows

    if headers:
        col_map = _detect_columns(headers)
    else:
        col_map = {"date": 0, "description": 1, "amount": 2, "debit": -1, "credit": -1, "balance": -1}

    transactions = []
    for row_idx, row in enumerate(data_rows):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if not any(cells):
            continue

        date_val = cells[col_map["date"]] if col_map["date"] >= 0 and col_map["date"] < len(cells) else ""
        desc_val = cells[col_map["description"]] if col_map["description"] >= 0 and col_map["description"] < len(cells) else ""

        amount_val = 0.0
        if col_map["debit"] >= 0 and col_map["credit"] >= 0:
            debit_str = cells[col_map["debit"]] if col_map["debit"] < len(cells) else ""
            credit_str = cells[col_map["credit"]] if col_map["credit"] < len(cells) else ""
            debit = _parse_number(debit_str) or 0.0
            credit = _parse_number(credit_str) or 0.0
            # credit - debit → deposit positive, withdrawal negative
            amount_val = credit - debit
        elif col_map["debit"] >= 0:
            debit_str = cells[col_map["debit"]] if col_map["debit"] < len(cells) else ""
            debit = _parse_number(debit_str) or 0.0
            amount_val = -debit
        elif col_map["credit"] >= 0:
            credit_str = cells[col_map["credit"]] if col_map["credit"] < len(cells) else ""
            credit = _parse_number(credit_str) or 0.0
            amount_val = credit
        elif col_map["amount"] >= 0 and col_map["amount"] < len(cells):
            parsed = _parse_number(cells[col_map["amount"]])
            if parsed is not None:
                amount_val = parsed

        # If no description column found, combine all non-date, non-amount cells
        if not desc_val and col_map["description"] == -1:
            skip_cols = {col_map["date"], col_map["amount"], col_map["debit"], col_map["credit"], col_map.get("balance", -1)}
            desc_parts = [cells[i] for i in range(len(cells)) if i not in skip_cols and cells[i]]
            desc_val = " ".join(desc_parts)

        if amount_val == 0.0 and not desc_val:
            continue

        transactions.append(Transaction(
            date=_normalize_date(date_val),
            description=desc_val,
            amount=round(amount_val, 2),
            row_number=row_idx + (2 if has_header else 1),
        ))

    return transactions


def _read_text_file(file_path: str) -> str:
    """Read a text-like file using common encodings used by banks."""
    encodings = ["utf-8-sig", "utf-8", "cp1256", "cp1252", "iso-8859-1"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return Path(file_path).read_text(encoding="utf-8", errors="ignore")


def parse_csv_file(file_path: str) -> List[Transaction]:
    """Parse transactions from a CSV/TSV/delimited text file."""
    content = _read_text_file(file_path)

    # Detect delimiter
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(content[:4096])
        delimiter = dialect.delimiter
    except csv.Error:
        ext = Path(file_path).suffix.lower()
        if ext == ".tsv":
            delimiter = "\t"
        elif "|" in content[:4096]:
            delimiter = "|"
        elif ";" in content[:4096]:
            delimiter = ";"
        else:
            delimiter = ","

    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)

    transactions = _extract_transactions_from_rows(rows, has_header=True)
    if transactions:
        return transactions
    return _extract_transactions_from_text(content)


def parse_xlsx_file(file_path: str) -> List[Transaction]:
    """Parse transactions from an XLSX/XLSM file (Office Open XML)."""
    import openpyxl

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return []

    rows = []
    for row in ws.iter_rows(values_only=True):
        cells = [str(c) if c is not None else "" for c in row]
        rows.append(cells)

    wb.close()
    return _extract_transactions_from_rows(rows, has_header=True)


def parse_xls_file(file_path: str) -> List[Transaction]:
    """Parse transactions from a legacy XLS file (BIFF format)."""
    import xlrd

    wb = xlrd.open_workbook(file_path)
    ws = wb.sheet_by_index(0)

    rows = []
    for row_idx in range(ws.nrows):
        row_cells = []
        for col in range(ws.ncols):
            cell_type = ws.cell_type(row_idx, col)
            cell_value = ws.cell_value(row_idx, col)
            if cell_type == xlrd.XL_CELL_DATE:
                try:
                    dt = xlrd.xldate_as_datetime(cell_value, wb.datemode)
                    row_cells.append(dt.strftime("%Y-%m-%d"))
                except Exception:
                    row_cells.append(str(cell_value))
            elif cell_value != "":
                row_cells.append(str(cell_value))
            else:
                row_cells.append("")
        rows.append(row_cells)

    return _extract_transactions_from_rows(rows, has_header=True)


def _rows_from_text_table(text: str) -> List[List[str]]:
    """Convert pasted/OCR text tables into rows using common bank separators."""
    rows: List[List[str]] = []
    for raw_line in text.splitlines():
        line = _to_western_digits(raw_line).strip()
        if not line:
            continue
        if "\t" in line:
            cells = [c.strip() for c in line.split("\t")]
        elif "|" in line:
            cells = [c.strip() for c in line.split("|")]
        elif ";" in line:
            cells = [c.strip() for c in line.split(";")]
        elif "," in line and line.count(",") >= 2:
            cells = [c.strip() for c in next(csv.reader([line]))]
        else:
            cells = [c.strip() for c in re.split(r"\s{2,}", line) if c.strip()]
        if cells:
            rows.append(cells)
    return rows


_DATE_RE = re.compile(
    r"(\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4}|\d{4}\d{2}\d{2})"
)
_AMOUNT_RE = re.compile(
    r"(?<!\d)([-(]?\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,2})?\)?|-?\d+(?:\.\d{1,2})?)(?!\d)"
)


def _extract_transactions_from_text(text: str) -> List[Transaction]:
    """Extract bank transactions from OCR/plain text when no reliable table exists."""
    rows = _rows_from_text_table(text)
    transactions = _extract_transactions_from_rows(rows, has_header=True)
    if transactions:
        return transactions

    txns: List[Transaction] = []
    debit_words = ["debit", "withdrawal", "paid out", "سحب", "مدين", "خصم", "صادر", "دفع"]
    credit_words = ["credit", "deposit", "paid in", "إيداع", "ايداع", "دائن", "وارد", "تحويل وارد"]

    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = _to_western_digits(raw_line).strip()
        if not line:
            continue

        date_match = _DATE_RE.search(line)
        if not date_match:
            continue

        date_text = date_match.group(1)
        normalized_date = _normalize_date(date_text)
        remainder = (line[:date_match.start()] + " " + line[date_match.end():]).strip()

        amount_candidates = []
        for m in _AMOUNT_RE.finditer(remainder):
            parsed = _parse_number(m.group(1))
            if parsed is None:
                continue
            # Filter obvious non-amount metadata, but keep normal small bank fees.
            if abs(parsed) == 0:
                continue
            if float(parsed).is_integer() and 1900 <= abs(parsed) <= 2100:
                continue
            amount_candidates.append((m.group(1), parsed, m.start(), m.end()))

        if not amount_candidates:
            continue

        # In text/PDF rows with a running balance, the transaction amount normally appears
        # before the balance. Prefer the first numeric amount after the date.
        amount_token, amount_val, start, end = amount_candidates[0]
        lower_line = line.lower()
        has_debit_signal = any(w in lower_line for w in debit_words)
        has_credit_signal = any(w in lower_line for w in credit_words)

        if has_debit_signal and not has_credit_signal:
            amount_val = -abs(amount_val)
        elif has_credit_signal and not has_debit_signal:
            amount_val = abs(amount_val)

        desc = (remainder[:start] + " " + remainder[end:]).strip()
        desc = re.sub(r"\b(SAR|SR|ر\.س|ريال|رس)\b", " ", desc, flags=re.IGNORECASE)
        desc = re.sub(r"\s+", " ", desc).strip()

        txns.append(Transaction(
            date=normalized_date,
            description=desc or line,
            amount=round(amount_val, 2),
            row_number=idx,
        ))

    return txns


def parse_text_file(file_path: str) -> List[Transaction]:
    """Parse transactions from TXT/TSV and MT940-like plain text exports."""
    return _extract_transactions_from_text(_read_text_file(file_path))


def parse_ofx_file(file_path: str) -> List[Transaction]:
    """Parse transactions from OFX/QFX bank exports."""
    text = _read_text_file(file_path)
    blocks = re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)", text, re.IGNORECASE | re.DOTALL)
    txns: List[Transaction] = []

    for idx, block in enumerate(blocks, start=1):
        def tag(name: str) -> str:
            m = re.search(rf"<{name}>([^\r\n<]+)", block, re.IGNORECASE)
            return m.group(1).strip() if m else ""

        date_val = _normalize_date(tag("DTPOSTED") or tag("DTUSER"))
        amount = _parse_number(tag("TRNAMT")) or 0.0
        description = " ".join(
            part for part in [tag("NAME"), tag("MEMO"), tag("CHECKNUM"), tag("FITID")]
            if part
        ).strip()

        if date_val and amount != 0.0:
            txns.append(Transaction(
                date=date_val,
                description=description or "OFX transaction",
                amount=round(amount, 2),
                row_number=idx,
            ))

    if txns:
        return txns

    return _extract_transactions_from_text(text)


def parse_qif_file(file_path: str) -> List[Transaction]:
    """Parse transactions from QIF bank exports."""
    text = _read_text_file(file_path)
    txns: List[Transaction] = []
    current: dict[str, str] = {}

    def flush(row_number: int) -> None:
        if not current:
            return
        amount = _parse_number(current.get("T", "")) or 0.0
        date_val = _normalize_date(current.get("D", ""))
        desc = " ".join(part for part in [current.get("P", ""), current.get("M", "")] if part).strip()
        if date_val and amount != 0.0:
            txns.append(Transaction(
                date=date_val,
                description=desc or "QIF transaction",
                amount=round(amount, 2),
                row_number=row_number,
            ))

    row = 0
    for raw_line in text.splitlines():
        row += 1
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

    flush(row + 1)
    return txns or _extract_transactions_from_text(text)


def _ocr_image_to_text(image) -> str:
    """OCR a PIL image using Arabic + English where available."""
    import pytesseract

    try:
        return pytesseract.image_to_string(image, lang="ara+eng")
    except Exception:
        return pytesseract.image_to_string(image)


def parse_image_file(file_path: str) -> List[Transaction]:
    """Parse transactions from scanned bank statement images."""
    from PIL import Image, ImageOps

    with Image.open(file_path) as img:
        normalized = ImageOps.exif_transpose(img)
        if normalized.mode not in ("RGB", "L"):
            normalized = normalized.convert("RGB")
        text = _ocr_image_to_text(normalized)

    return _extract_transactions_from_text(text)


def parse_pdf_file(file_path: str) -> List[Transaction]:
    """Parse transactions from digital or scanned PDF bank statements."""
    import fitz
    from PIL import Image

    doc = fitz.open(file_path)
    text_parts: list[str] = []

    try:
        for page in doc:
            page_text = page.get_text("text") or ""
            if page_text.strip():
                text_parts.append(page_text)

        digital_text = "\n".join(text_parts)
        digital_txns = _extract_transactions_from_text(digital_text)
        if digital_txns:
            return digital_txns

        ocr_parts: list[str] = []
        max_ocr_pages = min(len(doc), 25)
        for page_index in range(max_ocr_pages):
            page = doc[page_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_text = _ocr_image_to_text(image)
            if ocr_text.strip():
                ocr_parts.append(ocr_text)

        return _extract_transactions_from_text("\n".join(ocr_parts))
    finally:
        doc.close()


def parse_file(file_path: str) -> List[Transaction]:
    """Parse transactions from a file (auto-detect format)."""
    ext = Path(file_path).suffix.lower()

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

    if not transactions:
        supported_hint = ", ".join(get_supported_statement_extensions())
        raise ValueError(
            "No bank statement transactions could be extracted. "
            "Please upload a clearer statement or one of these formats: "
            f"{supported_hint}. For scanned PDFs/images, make sure Tesseract OCR is installed."
        )

    return transactions


def transactions_from_odoo_move_lines(move_lines: list) -> List[Transaction]:
    """Convert Odoo account.move.line records to Transaction objects.

    Odoo accounting convention for a bank account journal:
      debit  = money INTO the bank  (positive from customer perspective) → deposit
      credit = money OUT of the bank (negative from customer perspective) → withdrawal

    We convert to the unified sign convention:
      deposit  (debit in Odoo)  → positive
      withdrawal (credit in Odoo) → negative
    So: amount = debit - credit
    This matches the sign produced by _extract_transactions_from_rows (credit - debit
    on a bank statement where credit = deposit column, debit = withdrawal column).
    """
    transactions = []
    for idx, line in enumerate(move_lines):
        date_val = str(line.get("date", ""))
        name = line.get("name") or ""
        ref = line.get("ref") or ""
        description = name if name else ref
        if name and ref and name != ref:
            description = f"{name} - {ref}"

        debit = float(line.get("debit", 0))
        credit = float(line.get("credit", 0))
        # debit - credit so that money-in (Odoo debit) = positive,
        # money-out (Odoo credit) = negative. Consistent with statement parsing.
        amount = round(debit - credit, 2)

        if amount == 0.0:
            continue

        transactions.append(Transaction(
            date=_normalize_date(date_val),
            description=description,
            amount=amount,
            row_number=idx + 1,
        ))
    return transactions


def _smart_match(
    statement_only: List[Transaction],
    ledger_only: List[Transaction],
    confidence_threshold: float = 0.6,
) -> List[SmartMatch]:
    """Use LLM to match remaining unmatched transactions by description similarity."""
    if not statement_only or not ledger_only:
        return []

    # Limit to avoid excessively large prompts
    max_items = 30
    stmt_subset = statement_only[:max_items]
    ledg_subset = ledger_only[:max_items]

    stmt_lines = "\n".join(
        f"  S{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\""
        for i, t in enumerate(stmt_subset)
    )
    ledg_lines = "\n".join(
        f"  L{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\""
        for i, t in enumerate(ledg_subset)
    )

    system_prompt = (
        "You are a bank reconciliation assistant. You receive two lists of "
        "unmatched financial transactions: one from a bank statement and one "
        "from the accounting system (Odoo). Your job is to find likely matches "
        "based on description similarity, considering:\n"
        "- Arabic/English translations of the same entity\n"
        "- Abbreviations and partial matches\n"
        "- Similar dates (within ~7 days)\n"
        "- Amounts that are close but not exact (fees, rounding)\n"
        "Return ONLY a JSON array. Each element: "
        '{"s": <S-index>, "l": <L-index>, "confidence": <0.0-1.0>, "reason": "<brief explanation>"}\n'
        "Only include pairs with confidence >= 0.5. If no matches found, return [].\n"
        "Return raw JSON only, no markdown code blocks."
    )
    user_prompt = (
        f"Bank Statement (unmatched):\n{stmt_lines}\n\n"
        f"Accounting System (unmatched):\n{ledg_lines}"
    )

    try:
        from app.services.llm_service import chat
        raw = chat(system_prompt, user_prompt, temperature=0.0, timeout=60)
        if not raw:
            return []

        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        text = text.strip()

        pairs = json.loads(text)
        if not isinstance(pairs, list):
            return []

        results: List[SmartMatch] = []
        used_s: set[int] = set()
        used_l: set[int] = set()

        for pair in pairs:
            try:
                s_idx = int(pair.get("s", 0)) - 1
                l_idx = int(pair.get("l", 0)) - 1
                conf = float(pair.get("confidence", 0))
                reason = str(pair.get("reason", ""))
            except (TypeError, ValueError):
                continue

            if conf < confidence_threshold:
                continue
            if s_idx < 0 or s_idx >= len(stmt_subset):
                continue
            if l_idx < 0 or l_idx >= len(ledg_subset):
                continue
            if s_idx in used_s or l_idx in used_l:
                continue

            used_s.add(s_idx)
            used_l.add(l_idx)
            results.append(SmartMatch(
                statement_txn=stmt_subset[s_idx],
                ledger_txn=ledg_subset[l_idx],
                confidence=round(conf, 2),
                reason=reason,
            ))

        return results
    except Exception:
        return []


# Chart of accounts used for AI account suggestions (must match ACCOUNTS list in frontend)
_SUGGEST_ACCOUNTS_LIST = [
    {"code": "1010", "name": "النقدية والبنوك"},
    {"code": "1020", "name": "حساب جاري"},
    {"code": "4010", "name": "إيرادات المبيعات"},
    {"code": "5010", "name": "تكلفة البضاعة المباعة"},
    {"code": "6010", "name": "المصاريف العمومية"},
    {"code": "6020", "name": "رسوم بنكية"},
    {"code": "6030", "name": "فوائد بنكية"},
    {"code": "2010", "name": "دائنون تجاريون"},
    {"code": "1030", "name": "مدينون تجاريون"},
]


def _suggest_accounts(statement_only: List[Transaction]) -> List[Transaction]:
    """Use LLM to suggest the most appropriate account code for each statement-only transaction.

    Returns a new list of Transaction objects with ``ai_suggested_account`` populated
    where the LLM returned a valid account code.  Falls back to the original list if
    the LLM is unavailable or returns unparseable output.
    """
    if not statement_only:
        return statement_only

    max_items = 30
    subset = statement_only[:max_items]

    accounts_text = "\n".join(
        f"  {a['code']}: {a['name']}" for a in _SUGGEST_ACCOUNTS_LIST
    )
    txn_lines = "\n".join(
        f"  T{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\""
        for i, t in enumerate(subset)
    )
    valid_codes = {a["code"] for a in _SUGGEST_ACCOUNTS_LIST}

    system_prompt = (
        "You are an accounting assistant for a Saudi Arabian company. "
        "For each bank statement transaction, suggest the most appropriate "
        "account code from the chart of accounts below.\n"
        "Available accounts:\n"
        f"{accounts_text}\n\n"
        "Rules:\n"
        "- Bank fees/charges → 6020\n"
        "- Bank interest → 6030\n"
        "- Sales income / customer receipts → 4010\n"
        "- Supplier/vendor payments → 2010\n"
        "- General expenses → 6010\n"
        "- Cost of goods → 5010\n"
        "- Customer receivables → 1030\n"
        "- Default (unclear) → 6010\n"
        "Return ONLY a JSON array. Each element: "
        '{"t": <T-index>, "account": "<account_code>"}\n'
        "Return raw JSON only, no markdown code blocks."
    )
    user_prompt = f"Bank Statement Transactions:\n{txn_lines}"

    try:
        from app.services.llm_service import chat
        raw = chat(system_prompt, user_prompt, temperature=0.0, timeout=60)
        if not raw:
            return statement_only

        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        text = text.strip()

        suggestions = json.loads(text)
        if not isinstance(suggestions, list):
            return statement_only

        result = list(statement_only)
        for item in suggestions:
            try:
                t_idx = int(item.get("t", 0)) - 1
                account = str(item.get("account", "")).strip()
            except (TypeError, ValueError):
                continue
            if t_idx < 0 or t_idx >= len(result):
                continue
            if account not in valid_codes:
                continue
            result[t_idx] = result[t_idx].model_copy(update={"ai_suggested_account": account})

        # Return originals for items beyond the subset limit unchanged
        return result + list(statement_only[max_items:])
    except Exception:
        return statement_only


def _run_matching(
    statement_txns: List[Transaction],
    ledger_txns: List[Transaction],
) -> ReconciliationResult:
    """Core matching logic shared by all reconcile entry points."""

    # Track which ledger transactions have been matched
    ledger_matched = [False] * len(ledger_txns)
    statement_matched = [False] * len(statement_txns)
    matched_pairs: List[MatchedPair] = []

    # Pass 1: exact amount + exact date match
    for s_idx, s_txn in enumerate(statement_txns):
        if statement_matched[s_idx]:
            continue
        for l_idx, l_txn in enumerate(ledger_txns):
            if ledger_matched[l_idx]:
                continue
            if abs(s_txn.amount - l_txn.amount) < 0.01 and s_txn.date == l_txn.date:
                statement_matched[s_idx] = True
                ledger_matched[l_idx] = True
                matched_pairs.append(MatchedPair(statement_txn=s_txn, ledger_txn=l_txn))
                break

    # Pass 2: exact amount + date within 7-day window
    # FIX: replaced blind "same amount regardless of date" with a date-proximity check
    # to prevent false matches on recurring identical amounts (e.g. monthly rent).
    for s_idx, s_txn in enumerate(statement_txns):
        if statement_matched[s_idx]:
            continue
        for l_idx, l_txn in enumerate(ledger_txns):
            if ledger_matched[l_idx]:
                continue
            if abs(s_txn.amount - l_txn.amount) < 0.01:
                # Only match if both dates are valid and within 7 days of each other
                try:
                    s_date = datetime.strptime(s_txn.date, "%Y-%m-%d")
                    l_date = datetime.strptime(l_txn.date, "%Y-%m-%d")
                    if abs((s_date - l_date).days) <= 7:
                        statement_matched[s_idx] = True
                        ledger_matched[l_idx] = True
                        matched_pairs.append(MatchedPair(statement_txn=s_txn, ledger_txn=l_txn))
                        break
                except (ValueError, TypeError):
                    # If dates can't be parsed, skip to avoid false matches
                    continue

    statement_only = [t for i, t in enumerate(statement_txns) if not statement_matched[i]]
    ledger_only = [t for i, t in enumerate(ledger_txns) if not ledger_matched[i]]

    # Pass 3: AI-powered smart matching on remaining unmatched transactions
    smart_matches = _smart_match(statement_only, ledger_only)

    # Remove smart-matched transactions from the "only" lists
    smart_stmt_rows = {sm.statement_txn.row_number for sm in smart_matches}
    smart_ledg_rows = {sm.ledger_txn.row_number for sm in smart_matches}
    statement_only = [t for t in statement_only if t.row_number not in smart_stmt_rows]
    ledger_only = [t for t in ledger_only if t.row_number not in smart_ledg_rows]

    # Pass 4: AI account suggestion for statement-only transactions
    statement_only = _suggest_accounts(statement_only)

    stmt_total = sum(t.amount for t in statement_txns)
    ledg_total = sum(t.amount for t in ledger_txns)

    return ReconciliationResult(
        statement_only=statement_only,
        ledger_only=ledger_only,
        matched=matched_pairs,
        smart_matched=smart_matches,
        statement_total=round(stmt_total, 2),
        ledger_total=round(ledg_total, 2),
        difference=round(stmt_total - ledg_total, 2),
        statement_count=len(statement_txns),
        ledger_count=len(ledger_txns),
    )


def reconcile(statement_path: str, ledger_path: str) -> ReconciliationResult:
    """Compare bank statement file vs bank ledger file."""
    statement_txns = parse_file(statement_path)
    ledger_txns = parse_file(ledger_path)
    return _run_matching(statement_txns, ledger_txns)


def get_date_range(transactions: List[Transaction], buffer_days: int = 7) -> tuple:
    """Extract min/max dates from transactions for Odoo query scoping.

    Adds a buffer (default 7 days) on each side to allow Pass 2 matching
    for transactions posted near period boundaries.
    """
    from datetime import datetime, timedelta
    dates = [t.date for t in transactions if t.date and t.date >= "1900"]
    if not dates:
        return None, None
    min_date = datetime.strptime(min(dates), "%Y-%m-%d") - timedelta(days=buffer_days)
    max_date = datetime.strptime(max(dates), "%Y-%m-%d") + timedelta(days=buffer_days)
    return min_date.strftime("%Y-%m-%d"), max_date.strftime("%Y-%m-%d")


def reconcile_with_odoo_data(
    statement_path: str,
    odoo_move_lines: list,
) -> ReconciliationResult:
    """Compare bank statement file vs Odoo bank account transactions."""
    statement_txns = parse_file(statement_path)
    ledger_txns = transactions_from_odoo_move_lines(odoo_move_lines)
    return _run_matching(statement_txns, ledger_txns)
