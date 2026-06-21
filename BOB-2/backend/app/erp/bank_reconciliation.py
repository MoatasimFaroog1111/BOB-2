"""
Bank reconciliation engine.

Parses bank statement and bank ledger files (CSV/XLSX/XLS),
extracts transactions, and compares them to find discrepancies.
"""
import csv
import io
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


class Transaction(BaseModel):
    date: str
    description: str
    amount: float
    row_number: int


class ReconciliationResult(BaseModel):
    statement_only: List[Transaction]
    ledger_only: List[Transaction]
    matched: List[Transaction]
    statement_total: float
    ledger_total: float
    difference: float
    statement_count: int
    ledger_count: int


def _parse_number(value: str) -> Optional[float]:
    """Parse a number from a string, handling Arabic numerals and commas."""
    if not value or not value.strip():
        return None

    text = value.strip()

    # Convert Eastern Arabic numerals
    arabic_digits = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    western_digits = "0123456789"
    for a, w in zip(arabic_digits, western_digits):
        text = text.replace(a, w)

    # Remove currency symbols and whitespace
    text = re.sub(r"[^\d\.\-,]", "", text)
    text = text.replace(",", "")

    if not text or text in ("-", ".", "-."):
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _normalize_date(date_str: str) -> str:
    """Normalize date string to YYYY-MM-DD format."""
    if not date_str or not date_str.strip():
        return ""

    text = date_str.strip()

    # Convert Eastern Arabic numerals
    arabic_digits = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    western_digits = "0123456789"
    for a, w in zip(arabic_digits, western_digits):
        text = text.replace(a, w)

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # DD-MM-YYYY or DD/MM/YYYY
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", text)
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

    return text


def _detect_columns(headers: List[str]) -> dict:
    """Auto-detect which columns contain date, description, and amount."""
    date_keywords = ["date", "تاريخ", "التاريخ", "value date", "posting date"]
    desc_keywords = ["description", "الوصف", "البيان", "memo", "details", "تفاصيل", "narrative", "reference", "المرجع"]
    amount_keywords = ["amount", "المبلغ", "مبلغ", "debit", "credit", "مدين", "دائن", "balance", "الرصيد", "withdrawal", "deposit"]
    debit_keywords = ["debit", "مدين", "withdrawal", "سحب"]
    credit_keywords = ["credit", "دائن", "deposit", "إيداع"]

    result = {"date": -1, "description": -1, "amount": -1, "debit": -1, "credit": -1}

    for i, h in enumerate(headers):
        h_lower = h.lower().strip()
        if result["date"] == -1 and any(k in h_lower for k in date_keywords):
            result["date"] = i
        elif result["description"] == -1 and any(k in h_lower for k in desc_keywords):
            result["description"] = i
        elif result["debit"] == -1 and any(k in h_lower for k in debit_keywords):
            result["debit"] = i
        elif result["credit"] == -1 and any(k in h_lower for k in credit_keywords):
            result["credit"] = i
        elif result["amount"] == -1 and any(k in h_lower for k in amount_keywords):
            result["amount"] = i

    return result


def _extract_transactions_from_rows(rows: List[List[str]], has_header: bool = True) -> List[Transaction]:
    """Extract transactions from parsed rows."""
    if not rows or len(rows) < 2:
        return []

    headers = [str(c).strip() for c in rows[0]] if has_header else []
    data_rows = rows[1:] if has_header else rows

    if headers:
        col_map = _detect_columns(headers)
    else:
        col_map = {"date": 0, "description": 1, "amount": 2, "debit": -1, "credit": -1}

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
            amount_val = debit - credit
        elif col_map["amount"] >= 0 and col_map["amount"] < len(cells):
            parsed = _parse_number(cells[col_map["amount"]])
            if parsed is not None:
                amount_val = parsed

        if amount_val == 0.0 and not desc_val:
            continue

        # If no description column found, combine all non-date, non-amount cells
        if not desc_val and col_map["description"] == -1:
            skip_cols = {col_map["date"], col_map["amount"], col_map["debit"], col_map["credit"]}
            desc_parts = [cells[i] for i in range(len(cells)) if i not in skip_cols and cells[i]]
            desc_val = " ".join(desc_parts)

        transactions.append(Transaction(
            date=_normalize_date(date_val),
            description=desc_val,
            amount=round(amount_val, 2),
            row_number=row_idx + (2 if has_header else 1),
        ))

    return transactions


def parse_csv_file(file_path: str) -> List[Transaction]:
    """Parse transactions from a CSV file."""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # Detect delimiter
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(content[:4096])
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)

    return _extract_transactions_from_rows(rows, has_header=True)


def parse_xlsx_file(file_path: str) -> List[Transaction]:
    """Parse transactions from an XLSX file (Office Open XML)."""
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


def parse_file(file_path: str) -> List[Transaction]:
    """Parse transactions from a file (auto-detect format)."""
    ext = Path(file_path).suffix.lower()

    if ext == ".xlsx":
        return parse_xlsx_file(file_path)
    elif ext == ".xls":
        return parse_xls_file(file_path)
    elif ext == ".csv":
        return parse_csv_file(file_path)
    else:
        # Try CSV first, then XLSX, then XLS
        try:
            return parse_csv_file(file_path)
        except Exception:
            try:
                return parse_xlsx_file(file_path)
            except Exception:
                return parse_xls_file(file_path)


def reconcile(statement_path: str, ledger_path: str) -> ReconciliationResult:
    """
    Compare bank statement and bank ledger transactions.
    Returns transactions unique to each side and matched transactions.
    """
    statement_txns = parse_file(statement_path)
    ledger_txns = parse_file(ledger_path)

    # Track which ledger transactions have been matched
    ledger_matched = [False] * len(ledger_txns)
    statement_matched = [False] * len(statement_txns)
    matched_pairs: List[Transaction] = []

    # Pass 1: exact amount + date match
    for s_idx, s_txn in enumerate(statement_txns):
        if statement_matched[s_idx]:
            continue
        for l_idx, l_txn in enumerate(ledger_txns):
            if ledger_matched[l_idx]:
                continue
            if abs(s_txn.amount - l_txn.amount) < 0.01 and s_txn.date == l_txn.date:
                statement_matched[s_idx] = True
                ledger_matched[l_idx] = True
                matched_pairs.append(s_txn)
                break

    # Pass 2: exact amount match (date may differ by a few days)
    for s_idx, s_txn in enumerate(statement_txns):
        if statement_matched[s_idx]:
            continue
        for l_idx, l_txn in enumerate(ledger_txns):
            if ledger_matched[l_idx]:
                continue
            if abs(s_txn.amount - l_txn.amount) < 0.01:
                statement_matched[s_idx] = True
                ledger_matched[l_idx] = True
                matched_pairs.append(s_txn)
                break

    statement_only = [t for i, t in enumerate(statement_txns) if not statement_matched[i]]
    ledger_only = [t for i, t in enumerate(ledger_txns) if not ledger_matched[i]]

    stmt_total = sum(t.amount for t in statement_txns)
    ledg_total = sum(t.amount for t in ledger_txns)

    return ReconciliationResult(
        statement_only=statement_only,
        ledger_only=ledger_only,
        matched=matched_pairs,
        statement_total=round(stmt_total, 2),
        ledger_total=round(ledg_total, 2),
        difference=round(stmt_total - ledg_total, 2),
        statement_count=len(statement_txns),
        ledger_count=len(ledger_txns),
    )
