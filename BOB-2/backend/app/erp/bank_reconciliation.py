"""
Bank reconciliation engine.

Parses bank statement and bank ledger files (CSV/XLSX/XLS),
extracts transactions, and compares them to find discrepancies.

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


class Transaction(BaseModel):
    date: str
    description: str
    amount: float
    row_number: int


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
    """Auto-detect which columns contain date, description, and amount.

    Priority order for amount columns:
      1. Explicit debit column
      2. Explicit credit column
      3. Generic amount/balance column
    debit/credit keywords are intentionally separated from amount_keywords
    to avoid double-detection conflicts.
    """
    date_keywords = ["date", "\u062a\u0627\u0631\u064a\u062e", "\u0627\u0644\u062a\u0627\u0631\u064a\u062e", "value date", "posting date"]
    desc_keywords = ["description", "\u0627\u0644\u0648\u0635\u0641", "\u0627\u0644\u0628\u064a\u0627\u0646", "memo", "details", "\u062a\u0641\u0627\u0635\u064a\u0644", "narrative", "reference", "\u0627\u0644\u0645\u0631\u062c\u0639"]
    # FIX: removed "debit"/"credit" from amount_keywords to avoid conflict with debit/credit columns
    amount_keywords = ["amount", "\u0627\u0644\u0645\u0628\u0644\u063a", "\u0645\u0628\u0644\u063a", "balance", "\u0627\u0644\u0631\u0635\u064a\u062f", "withdrawal", "deposit"]
    debit_keywords = ["debit", "\u0645\u062f\u064a\u0646", "withdrawal", "\u0633\u062d\u0628"]
    credit_keywords = ["credit", "\u062f\u0627\u0626\u0646", "deposit", "\u0625\u064a\u062f\u0627\u0639"]

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
    """Extract transactions from parsed rows.

    Amount sign convention (matches Odoo and bank statement):
      deposit  (credit / money-in)  → positive
      withdrawal (debit / money-out) → negative
    When separate debit/credit columns exist: amount = credit - debit
    When a single signed amount column exists: value is used as-is.
    """
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
            # FIX: credit - debit → deposit positive, withdrawal negative
            # This aligns with Odoo convention and standard bank statement sign
            amount_val = credit - debit
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
        # FIX: debit - credit so that money-in (Odoo debit) = positive,
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
        '{\"s\": <S-index>, \"l\": <L-index>, \"confidence\": <0.0-1.0>, \"reason\": \"<brief explanation>\"}\n'
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
