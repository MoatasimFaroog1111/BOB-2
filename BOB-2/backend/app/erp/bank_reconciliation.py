"""Bank reconciliation engine.

Parses bank statement files, converts them into real transactions, and compares
them with Odoo bank ledger lines.

Amount convention:
- money into bank: positive
- money out of bank: negative
"""
import csv
import io
import json
import re
from datetime import datetime, timedelta
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


def get_supported_statement_extensions() -> List[str]:
    return sorted(SUPPORTED_BANK_STATEMENT_EXTENSIONS)


def _to_western_digits(value: str) -> str:
    return str(value or "").translate(str.maketrans({
        "٠":"0","١":"1","٢":"2","٣":"3","٤":"4","٥":"5","٦":"6","٧":"7","٨":"8","٩":"9",
        "۰":"0","۱":"1","۲":"2","۳":"3","۴":"4","۵":"5","۶":"6","۷":"7","۸":"8","۹":"9",
        "٬":",","،":",","٫":".",
    }))


def _parse_number(value: str) -> Optional[float]:
    raw = _to_western_digits(str(value or "")).strip()
    if not raw:
        return None
    negative_brackets = raw.startswith("(") and raw.endswith(")")
    text = re.sub(r"[^\d.,()\-]", "", raw).replace(",", "").replace("(", "").replace(")", "")
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        parsed = float(text)
        return -parsed if negative_brackets and parsed > 0 else parsed
    except ValueError:
        return None


def _normalize_date(date_str: str) -> str:
    text = _to_western_digits(str(date_str or "")).strip()
    if not text:
        return ""

    months = {
        "january":"01","february":"02","march":"03","april":"04","may":"05","june":"06","july":"07","august":"08","september":"09","october":"10","november":"11","december":"12",
        "jan":"01","feb":"02","mar":"03","apr":"04","jun":"06","jul":"07","aug":"08","sep":"09","sept":"09","oct":"10","nov":"11","dec":"12",
        "يناير":"01","فبراير":"02","مارس":"03","أبريل":"04","ابريل":"04","مايو":"05","يونيو":"06","يونيه":"06","يوليو":"07","يوليه":"07","أغسطس":"08","اغسطس":"08","سبتمبر":"09","أكتوبر":"10","اكتوبر":"10","نوفمبر":"11","ديسمبر":"12",
    }
    low = text.lower()
    for name, num in months.items():
        if name in low:
            m = re.search(r"\b(\d{1,2})\b.*\b(\d{4})\b", text)
            if m:
                try:
                    return datetime(int(m.group(2)), int(num), int(m.group(1))).strftime("%Y-%m-%d")
                except ValueError:
                    pass

    patterns = [
        (r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", "ymd"),
        (r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", "dmy"),
        (r"\b(\d{4})(\d{2})(\d{2})\b", "ymd"),
    ]
    for pattern, kind in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            if kind == "ymd":
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
            first, second, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            day, month = (second, first) if second > 12 else (first, second)
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


_DATE_RE = re.compile(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{8})")
_MONEY_RE = re.compile(r"(?<!\d)(\(?-?\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,2})?\)?|\(?-?\d+\.\d{1,4}\)?)(?!\d)")

_SUMMARY_WORDS = [
    "opening balance", "closing balance", "available balance", "running balance", "statement summary",
    "total debit", "total credit", "total deposits", "total withdrawals", "account number", "iban", "page ",
    "الرصيد الافتتاحي", "الرصيد الختامي", "الرصيد المتاح", "إجمالي", "اجمالي", "مجموع", "رقم الحساب", "ايبان", "آيبان",
]
_DEBIT_WORDS = ["debit", "withdrawal", "paid out", "dr", "سحب", "مدين", "خصم", "دفع"]
_CREDIT_WORDS = ["credit", "deposit", "paid in", "cr", "إيداع", "ايداع", "دائن", "وارد"]


def _is_summary_text(text: str) -> bool:
    low = _to_western_digits(text).lower()
    return any(word in low for word in _SUMMARY_WORDS)


def _detect_columns(headers: List[str]) -> dict:
    result = {"date": -1, "description": -1, "amount": -1, "debit": -1, "credit": -1, "balance": -1}
    date_words = ["date", "تاريخ", "value date", "posting date", "transaction date", "تاريخ العملية"]
    desc_words = ["description", "الوصف", "البيان", "memo", "details", "تفاصيل", "narrative", "reference", "المرجع", "remarks"]
    amount_words = ["amount", "المبلغ", "مبلغ", "transaction amount", "net amount"]
    debit_words = ["debit", "مدين", "withdrawal", "سحب", "خصم", "paid out"]
    credit_words = ["credit", "دائن", "deposit", "إيداع", "ايداع", "paid in"]
    balance_words = ["balance", "الرصيد", "running balance", "available balance"]
    for i, header in enumerate(headers):
        h = str(header or "").lower().strip()
        if result["date"] == -1 and any(w in h for w in date_words):
            result["date"] = i
        elif result["description"] == -1 and any(w in h for w in desc_words):
            result["description"] = i
        elif result["debit"] == -1 and any(w in h for w in debit_words):
            result["debit"] = i
        elif result["credit"] == -1 and any(w in h for w in credit_words):
            result["credit"] = i
        elif result["balance"] == -1 and any(w in h for w in balance_words):
            result["balance"] = i
        elif result["amount"] == -1 and any(w in h for w in amount_words):
            result["amount"] = i
    return result


def _find_header_row_index(rows: List[List[str]], max_scan_rows: int = 30) -> int:
    best_idx = 0
    best_score = -1
    for idx, row in enumerate(rows[:max_scan_rows]):
        headers = [str(c).strip() if c is not None else "" for c in row]
        if not any(headers):
            continue
        col = _detect_columns(headers)
        score = 0
        if col["date"] >= 0:
            score += 2
        if col["amount"] >= 0 or col["debit"] >= 0 or col["credit"] >= 0:
            score += 2
        if col["description"] >= 0:
            score += 1
        if score > best_score:
            best_score = score
            best_idx = idx
        if score >= 4:
            return idx
    return best_idx


def _amount_candidates(text: str) -> list[dict]:
    normalized = _to_western_digits(text)
    out = []
    for match in _MONEY_RE.finditer(normalized):
        token = match.group(1)
        value = _parse_number(token)
        if value is None or value == 0:
            continue
        if float(value).is_integer() and 1900 <= abs(value) <= 2100:
            continue
        out.append({"token": token, "amount": value, "start": match.start(1), "end": match.end(1)})
    return out


def _extract_transactions_from_unstructured_rows(rows: List[List[str]]) -> List[Transaction]:
    transactions: List[Transaction] = []
    for idx, row in enumerate(rows, start=1):
        cells = [str(c).strip() for c in row if str(c).strip()]
        if not cells:
            continue
        row_text = " ".join(cells)
        if _is_summary_text(row_text):
            continue
        date_token = ""
        normalized_date = ""
        for cell in cells:
            normalized_date = _normalize_date(cell)
            if normalized_date:
                found = _DATE_RE.search(_to_western_digits(cell))
                date_token = found.group(1) if found else cell
                break
        if not normalized_date:
            continue
        candidates = _amount_candidates(row_text)
        if not candidates:
            continue
        selected = dict(candidates[0])
        low = row_text.lower()
        if any(w in low for w in _DEBIT_WORDS) and not any(w in low for w in _CREDIT_WORDS):
            selected["amount"] = -abs(float(selected["amount"]))
        elif any(w in low for w in _CREDIT_WORDS) and not any(w in low for w in _DEBIT_WORDS):
            selected["amount"] = abs(float(selected["amount"]))
        desc = _to_western_digits(row_text).replace(date_token, " ", 1).replace(str(selected["token"]), " ", 1)
        desc = re.sub(r"\b(SAR|SR|RIYAL|ر\.س|ريال|رس)\b", " ", desc, flags=re.IGNORECASE)
        desc = re.sub(r"\s+", " ", desc).strip(" -|,؛:.")
        if not desc or _is_summary_text(desc):
            continue
        transactions.append(Transaction(date=normalized_date, description=desc, amount=round(float(selected["amount"]), 2), row_number=idx))
    return transactions


def _extract_transactions_from_rows(rows: List[List[str]], has_header: bool = True) -> List[Transaction]:
    if not rows or len(rows) < 2:
        return []
    if has_header:
        header_idx = _find_header_row_index(rows)
        headers = [str(c).strip() if c is not None else "" for c in rows[header_idx]]
        data_rows = rows[header_idx + 1:]
    else:
        headers = []
        data_rows = rows
    col = _detect_columns(headers) if headers else {"date": 0, "description": 1, "amount": 2, "debit": -1, "credit": -1, "balance": -1}
    if col["date"] < 0 or (col["amount"] < 0 and col["debit"] < 0 and col["credit"] < 0):
        return _extract_transactions_from_unstructured_rows(rows)
    txns: List[Transaction] = []
    for row_idx, row in enumerate(data_rows):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if not any(cells):
            continue
        if _is_summary_text(" ".join(cells)):
            continue
        date_val = cells[col["date"]] if 0 <= col["date"] < len(cells) else ""
        normalized_date = _normalize_date(date_val)
        if not normalized_date:
            continue
        desc = cells[col["description"]] if 0 <= col["description"] < len(cells) else ""
        amount = None
        if col["debit"] >= 0 and col["credit"] >= 0:
            debit = _parse_number(cells[col["debit"]]) if col["debit"] < len(cells) else None
            credit = _parse_number(cells[col["credit"]]) if col["credit"] < len(cells) else None
            debit = debit or 0.0
            credit = credit or 0.0
            if debit or credit:
                amount = credit - debit
        elif col["debit"] >= 0 and col["debit"] < len(cells):
            debit = _parse_number(cells[col["debit"]])
            if debit:
                amount = -abs(debit)
        elif col["credit"] >= 0 and col["credit"] < len(cells):
            credit = _parse_number(cells[col["credit"]])
            if credit:
                amount = abs(credit)
        elif col["amount"] >= 0 and col["amount"] < len(cells):
            amount = _parse_number(cells[col["amount"]])
        if amount is None or round(amount, 2) == 0:
            continue
        if not desc:
            skip = {col["date"], col["amount"], col["debit"], col["credit"], col.get("balance", -1)}
            desc = " ".join(cells[i] for i in range(len(cells)) if i not in skip and cells[i]).strip()
        if not desc or _is_summary_text(desc):
            continue
        txns.append(Transaction(date=normalized_date, description=desc, amount=round(amount, 2), row_number=row_idx + (2 if has_header else 1)))
    return txns or _extract_transactions_from_unstructured_rows(rows)


def _read_text_file(file_path: str) -> str:
    last_error = None
    for encoding in ["utf-8-sig", "utf-8", "cp1256", "cp1252", "iso-8859-1"]:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return Path(file_path).read_text(encoding="utf-8", errors="ignore")


def _rows_from_text(text: str) -> List[List[str]]:
    rows = []
    for line in text.splitlines():
        line = _to_western_digits(line).strip()
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
        rows.append(cells or [line])
    return rows


def parse_csv_file(file_path: str) -> List[Transaction]:
    content = _read_text_file(file_path)
    try:
        delimiter = csv.Sniffer().sniff(content[:4096]).delimiter
    except csv.Error:
        ext = Path(file_path).suffix.lower()
        delimiter = "\t" if ext == ".tsv" else "|" if "|" in content[:4096] else ";" if ";" in content[:4096] else ","
    rows = list(csv.reader(io.StringIO(content), delimiter=delimiter))
    return _extract_transactions_from_rows(rows, has_header=True) or _extract_transactions_from_unstructured_rows(_rows_from_text(content))


def parse_xlsx_file(file_path: str) -> List[Transaction]:
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return []
    rows = [[str(c) if c is not None else "" for c in row] for row in ws.iter_rows(values_only=True)]
    wb.close()
    return _extract_transactions_from_rows(rows, has_header=True)


def parse_xls_file(file_path: str) -> List[Transaction]:
    import xlrd
    wb = xlrd.open_workbook(file_path)
    ws = wb.sheet_by_index(0)
    rows = []
    for row_idx in range(ws.nrows):
        row_cells = []
        for col in range(ws.ncols):
            cell_type = ws.cell_type(row_idx, col)
            value = ws.cell_value(row_idx, col)
            if cell_type == xlrd.XL_CELL_DATE:
                try:
                    row_cells.append(xlrd.xldate_as_datetime(value, wb.datemode).strftime("%Y-%m-%d"))
                except Exception:
                    row_cells.append(str(value))
            else:
                row_cells.append(str(value) if value != "" else "")
        rows.append(row_cells)
    return _extract_transactions_from_rows(rows, has_header=True)


def parse_text_file(file_path: str) -> List[Transaction]:
    return _extract_transactions_from_rows(_rows_from_text(_read_text_file(file_path)), has_header=True)


def parse_ofx_file(file_path: str) -> List[Transaction]:
    text = _read_text_file(file_path)
    blocks = re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)", text, re.IGNORECASE | re.DOTALL)
    txns: List[Transaction] = []
    for idx, block in enumerate(blocks, start=1):
        def tag(name: str) -> str:
            m = re.search(rf"<{name}>([^\r\n<]+)", block, re.IGNORECASE)
            return m.group(1).strip() if m else ""
        date_val = _normalize_date(tag("DTPOSTED") or tag("DTUSER"))
        amount = _parse_number(tag("TRNAMT")) or 0.0
        description = " ".join(part for part in [tag("NAME"), tag("MEMO"), tag("CHECKNUM"), tag("FITID")] if part).strip()
        if date_val and amount and description:
            txns.append(Transaction(date=date_val, description=description, amount=round(amount, 2), row_number=idx))
    return txns or _extract_transactions_from_unstructured_rows(_rows_from_text(text))


def parse_qif_file(file_path: str) -> List[Transaction]:
    text = _read_text_file(file_path)
    txns: List[Transaction] = []
    current: dict[str, str] = {}
    def flush(row_number: int) -> None:
        if not current:
            return
        amount = _parse_number(current.get("T", "")) or 0.0
        date_val = _normalize_date(current.get("D", ""))
        desc = " ".join(part for part in [current.get("P", ""), current.get("M", "")] if part).strip()
        if date_val and amount and desc:
            txns.append(Transaction(date=date_val, description=desc, amount=round(amount, 2), row_number=row_number))
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
    return txns or _extract_transactions_from_unstructured_rows(_rows_from_text(text))


def _ocr_image_to_text(image) -> str:
    import pytesseract
    try:
        return pytesseract.image_to_string(image, lang="ara+eng")
    except Exception:
        return pytesseract.image_to_string(image)


def parse_image_file(file_path: str) -> List[Transaction]:
    from PIL import Image, ImageOps
    with Image.open(file_path) as img:
        normalized = ImageOps.exif_transpose(img)
        if normalized.mode not in ("RGB", "L"):
            normalized = normalized.convert("RGB")
        text = _ocr_image_to_text(normalized)
    return _extract_transactions_from_unstructured_rows(_rows_from_text(text))


def parse_pdf_file(file_path: str) -> List[Transaction]:
    from app.erp.pdf_statement_parser import parse_pdf_statement
    return parse_pdf_statement(file_path, Transaction, _ocr_image_to_text)


def parse_file(file_path: str) -> List[Transaction]:
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
        supported = ", ".join(get_supported_statement_extensions())
        raise ValueError(
            "No real bank transactions were extracted from the uploaded document. "
            "The file must contain transaction rows with date, description, and movement amount. "
            f"Supported formats: {supported}."
        )
    return transactions


def transactions_from_odoo_move_lines(move_lines: list) -> List[Transaction]:
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
        amount = round(debit - credit, 2)
        if amount == 0.0:
            continue
        transactions.append(Transaction(date=_normalize_date(date_val), description=description, amount=amount, row_number=idx + 1))
    return transactions


def _smart_match(statement_only: List[Transaction], ledger_only: List[Transaction], confidence_threshold: float = 0.6) -> List[SmartMatch]:
    if not statement_only or not ledger_only:
        return []
    max_items = 30
    stmt_subset = statement_only[:max_items]
    ledg_subset = ledger_only[:max_items]
    stmt_lines = "\n".join(f"S{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\"" for i, t in enumerate(stmt_subset))
    ledg_lines = "\n".join(f"L{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\"" for i, t in enumerate(ledg_subset))
    system_prompt = (
        "You are a bank reconciliation assistant. Find likely matches between uploaded bank statement transactions and Odoo ledger transactions. "
        "Consider amount, date proximity, Arabic/English descriptions, abbreviations, and rounding. "
        "Return only JSON array: [{\"s\":1,\"l\":1,\"confidence\":0.8,\"reason\":\"...\"}]."
    )
    user_prompt = f"Bank Statement:\n{stmt_lines}\n\nOdoo Ledger:\n{ledg_lines}"
    try:
        from app.services.llm_service import chat
        raw = chat(system_prompt, user_prompt, temperature=0.0, timeout=60)
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


_SUGGEST_ACCOUNTS_LIST = [
    {"code":"1010","name":"النقدية والبنوك"},
    {"code":"1020","name":"حساب جاري"},
    {"code":"4010","name":"إيرادات المبيعات"},
    {"code":"5010","name":"تكلفة البضاعة المباعة"},
    {"code":"6010","name":"المصاريف العمومية"},
    {"code":"6020","name":"رسوم بنكية"},
    {"code":"6030","name":"فوائد بنكية"},
    {"code":"2010","name":"دائنون تجاريون"},
    {"code":"1030","name":"مدينون تجاريون"},
]


def _suggest_accounts(statement_only: List[Transaction]) -> List[Transaction]:
    if not statement_only:
        return statement_only
    subset = statement_only[:30]
    accounts_text = "\n".join(f"{a['code']}: {a['name']}" for a in _SUGGEST_ACCOUNTS_LIST)
    txn_lines = "\n".join(f"T{i+1}: date={t.date} amount={t.amount} desc=\"{t.description}\"" for i, t in enumerate(subset))
    valid_codes = {a["code"] for a in _SUGGEST_ACCOUNTS_LIST}
    system_prompt = f"Suggest account code for each bank transaction from this chart:\n{accounts_text}\nReturn only JSON array: [{{\"t\":1,\"account\":\"6020\"}}]."
    try:
        from app.services.llm_service import chat
        raw = chat(system_prompt, f"Transactions:\n{txn_lines}", temperature=0.0, timeout=60)
        if not raw:
            return statement_only
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        suggestions = json.loads(text.strip())
        if not isinstance(suggestions, list):
            return statement_only
        result = list(statement_only)
        for item in suggestions:
            try:
                idx = int(item.get("t", 0)) - 1
                account = str(item.get("account", "")).strip()
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(result) and account in valid_codes:
                result[idx] = result[idx].model_copy(update={"ai_suggested_account": account})
        return result + list(statement_only[30:])
    except Exception:
        return statement_only


def _run_matching(statement_txns: List[Transaction], ledger_txns: List[Transaction]) -> ReconciliationResult:
    ledger_matched = [False] * len(ledger_txns)
    statement_matched = [False] * len(statement_txns)
    matched_pairs: List[MatchedPair] = []
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
    for s_idx, s_txn in enumerate(statement_txns):
        if statement_matched[s_idx]:
            continue
        for l_idx, l_txn in enumerate(ledger_txns):
            if ledger_matched[l_idx]:
                continue
            if abs(s_txn.amount - l_txn.amount) < 0.01:
                try:
                    s_date = datetime.strptime(s_txn.date, "%Y-%m-%d")
                    l_date = datetime.strptime(l_txn.date, "%Y-%m-%d")
                    if abs((s_date - l_date).days) <= 7:
                        statement_matched[s_idx] = True
                        ledger_matched[l_idx] = True
                        matched_pairs.append(MatchedPair(statement_txn=s_txn, ledger_txn=l_txn))
                        break
                except (ValueError, TypeError):
                    continue
    statement_only = [t for i, t in enumerate(statement_txns) if not statement_matched[i]]
    ledger_only = [t for i, t in enumerate(ledger_txns) if not ledger_matched[i]]
    smart_matches = _smart_match(statement_only, ledger_only)
    smart_stmt_rows = {sm.statement_txn.row_number for sm in smart_matches}
    smart_ledg_rows = {sm.ledger_txn.row_number for sm in smart_matches}
    statement_only = [t for t in statement_only if t.row_number not in smart_stmt_rows]
    ledger_only = [t for t in ledger_only if t.row_number not in smart_ledg_rows]
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
