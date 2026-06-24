from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d")


class BankStatementLine(BaseModel):
    line_id: str
    transaction_date: str
    value_date: str | None = None
    description: str
    debit: float = 0.0
    credit: float = 0.0
    balance: float | None = None
    reference: str | None = None
    counterparty: str | None = None
    row_number: int

    @property
    def amount(self) -> float:
        return round(self.credit - self.debit, 2)


class OdooBankLedgerLine(BaseModel):
    line_id: str
    move_date: str
    posting_date: str | None = None
    journal_entry_number: str | None = None
    label: str
    partner: str | None = None
    debit: float = 0.0
    credit: float = 0.0
    balance: float = 0.0
    amount: float = 0.0
    currency: str | None = None
    payment_reference: str | None = None
    move_id: int | None = None
    account_id: int | None = None
    journal_id: int | None = None
    reconciliation_status: str | None = None


class MatchLine(BaseModel):
    bank_line: BankStatementLine
    odoo_line: OdooBankLedgerLine
    match_status: str
    confidence_score: int = Field(ge=0, le=100)
    match_reason: str
    compared_fields: dict[str, Any]


class UnmatchedBankLine(BaseModel):
    bank_line: BankStatementLine
    suggested_action: str
    reason: str


class MissingOdooLine(BaseModel):
    odoo_line: OdooBankLedgerLine
    suggested_action: str
    reason: str


class AmountMismatch(BaseModel):
    bank_line: BankStatementLine
    odoo_line: OdooBankLedgerLine
    amount_difference: float
    likely_reason: str
    confidence_score: int = Field(ge=0, le=100)
    compared_fields: dict[str, Any]


class DuplicateRisk(BaseModel):
    bank_line: BankStatementLine | None = None
    odoo_line: OdooBankLedgerLine | None = None
    possible_odoo_matches: list[OdooBankLedgerLine] = []
    possible_bank_matches: list[BankStatementLine] = []
    reason: str


class ReconciliationSummary(BaseModel):
    total_bank_statement_lines: int
    total_odoo_ledger_lines: int
    exact_matches_count: int
    strong_matches_count: int
    possible_matches_count: int
    unmatched_bank_lines_count: int
    missing_in_bank_statement_count: int
    amount_mismatch_count: int
    duplicate_risk_count: int
    bank_total_debit: float
    bank_total_credit: float
    odoo_total_debit: float
    odoo_total_credit: float
    net_difference: float


class BankReconciliationReport(BaseModel):
    summary: ReconciliationSummary
    matched_lines: list[MatchLine]
    unmatched_bank_lines: list[UnmatchedBankLine]
    missing_in_bank_statement: list[MissingOdooLine]
    amount_mismatches: list[AmountMismatch]
    duplicate_risks: list[DuplicateRisk]
    errors: list[str] = []
    warnings: list[str] = []


def _arabic_to_western(value: str) -> str:
    for a, w in zip("٠١٢٣٤٥٦٧٨٩", "0123456789"):
        value = value.replace(a, w)
    return value


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _arabic_to_western(str(value)).strip()
    if not text or text in {"-", "—"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^\d.,\-]", "", text).replace(",", "")
    if not text or text in {"-", "."}:
        return None
    try:
        number = float(text)
        return -abs(number) if negative else number
    except ValueError:
        return None


def normalize_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = _arabic_to_western(str(value or "")).strip()
    if not text:
        return ""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).strftime("%Y-%m-%d")
    match = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", text)
    if match:
        return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).strftime("%Y-%m-%d")
    return text


def _norm(text: str | None) -> str:
    text = (text or "").lower()
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"[ى]", "ي", text)
    text = re.sub(r"[ة]", "ه", text)
    return re.sub(r"[^\w\u0600-\u06ff]+", " ", text).strip()


def text_similarity(left_text: str | None, *right_parts: str | None) -> float:
    left = _norm(left_text)
    right = _norm(" ".join(part or "" for part in right_parts))
    if not left or not right:
        return 0.0
    ratio = SequenceMatcher(None, left, right).ratio()
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return max(ratio, overlap)


def _detect_columns(headers: list[str]) -> dict[str, int]:
    aliases = {
        "transaction_date": ["transaction date", "posting date", "date", "تاريخ العملية", "التاريخ", "تاريخ"],
        "value_date": ["value date", "تاريخ القيمة"],
        "description": ["description", "narrative", "details", "memo", "البيان", "الوصف", "تفاصيل"],
        "debit": ["debit", "withdrawal", "dr", "مدين", "سحب"],
        "credit": ["credit", "deposit", "cr", "دائن", "ايداع", "إيداع"],
        "amount": ["amount", "المبلغ"],
        "balance": ["balance", "الرصيد"],
        "reference": ["reference", "ref", "payment reference", "المرجع", "رقم المرجع"],
        "counterparty": ["counterparty", "partner", "beneficiary", "المستفيد", "الطرف"],
    }
    result = {key: -1 for key in aliases}
    for idx, header in enumerate(headers):
        normalized = _norm(header)
        for key, names in aliases.items():
            if result[key] == -1 and any(_norm(name) in normalized for name in names):
                result[key] = idx
    return result


def _rows_to_bank_lines(rows: list[list[Any]]) -> list[BankStatementLine]:
    if len(rows) < 2:
        raise ValueError("Invalid bank statement format: no transaction rows found.")
    headers = [str(c or "").strip() for c in rows[0]]
    col = _detect_columns(headers)
    if col["transaction_date"] == -1 or (col["description"] == -1 and col["reference"] == -1):
        raise ValueError("Invalid bank statement format: date and description/reference columns are required.")
    lines: list[BankStatementLine] = []
    for row_index, row in enumerate(rows[1:], start=2):
        cells = [row[i] if i < len(row) else "" for i in range(max(len(row), len(headers)))]
        debit = parse_number(cells[col["debit"]]) if col["debit"] >= 0 else 0.0
        credit = parse_number(cells[col["credit"]]) if col["credit"] >= 0 else 0.0
        if (debit is None or debit == 0) and (credit is None or credit == 0) and col["amount"] >= 0:
            amount = parse_number(cells[col["amount"]]) or 0.0
            debit = abs(amount) if amount < 0 else 0.0
            credit = amount if amount > 0 else 0.0
        debit = round(float(debit or 0), 2)
        credit = round(float(credit or 0), 2)
        desc = str(cells[col["description"]] if col["description"] >= 0 else "").strip()
        ref = str(cells[col["reference"]] if col["reference"] >= 0 else "").strip() or None
        if not desc and ref:
            desc = ref
        if not desc and debit == 0 and credit == 0:
            continue
        lines.append(BankStatementLine(
            line_id=f"B{row_index}", transaction_date=normalize_date(cells[col["transaction_date"]]),
            value_date=normalize_date(cells[col["value_date"]]) if col["value_date"] >= 0 else None,
            description=desc, debit=debit, credit=credit,
            balance=parse_number(cells[col["balance"]]) if col["balance"] >= 0 else None,
            reference=ref,
            counterparty=str(cells[col["counterparty"]]).strip() if col["counterparty"] >= 0 and str(cells[col["counterparty"]]).strip() else None,
            row_number=row_index,
        ))
    if not lines:
        raise ValueError("Invalid bank statement format: no valid bank statement lines parsed.")
    return lines


def parse_bank_statement_text(text: str) -> list[BankStatementLine]:
    sample = text.strip()
    if not sample:
        raise ValueError("Invalid bank statement format: pasted text is empty.")
    try:
        dialect = csv.Sniffer().sniff(sample[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ","
    rows = [row for row in csv.reader(io.StringIO(sample), delimiter=delimiter) if any(str(c).strip() for c in row)]
    return _rows_to_bank_lines(rows)


def parse_bank_statement_file(path: str) -> list[BankStatementLine]:
    ext = Path(path).suffix.lower()
    if ext in {".csv", ".txt"}:
        return parse_bank_statement_text(Path(path).read_text(encoding="utf-8-sig"))
    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = [[cell for cell in row] for row in ws.iter_rows(values_only=True)] if ws else []
        wb.close()
        return _rows_to_bank_lines(rows)
    if ext == ".xls":
        import xlrd
        wb = xlrd.open_workbook(path)
        ws = wb.sheet_by_index(0)
        rows = [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in range(ws.nrows)]
        return _rows_to_bank_lines(rows)
    raise ValueError("Invalid bank statement format: supported file types are CSV, TXT, XLSX, and XLS.")


def odoo_lines_from_move_lines(move_lines: list[dict[str, Any]]) -> list[OdooBankLedgerLine]:
    result: list[OdooBankLedgerLine] = []
    for line in move_lines:
        debit = round(float(line.get("debit") or 0), 2)
        credit = round(float(line.get("credit") or 0), 2)
        move = line.get("move_id") if isinstance(line.get("move_id"), list) else [line.get("move_id"), None]
        account = line.get("account_id") if isinstance(line.get("account_id"), list) else [line.get("account_id"), None]
        journal = line.get("journal_id") if isinstance(line.get("journal_id"), list) else [line.get("journal_id"), None]
        partner = line.get("partner_id") if isinstance(line.get("partner_id"), list) else [line.get("partner_id"), None]
        currency = line.get("currency_id") if isinstance(line.get("currency_id"), list) else [line.get("currency_id"), None]
        matched = bool(line.get("matched_debit_ids") or line.get("matched_credit_ids") or line.get("full_reconcile_id"))
        result.append(OdooBankLedgerLine(
            line_id=f"O{line.get('id')}", move_date=normalize_date(line.get("date")), posting_date=normalize_date(line.get("date_maturity")) or None,
            journal_entry_number=move[1] or line.get("move_name") or line.get("ref"), label=line.get("name") or line.get("ref") or "",
            partner=partner[1], debit=debit, credit=credit, balance=round(float(line.get("balance") or debit - credit), 2),
            amount=round(debit - credit, 2), currency=currency[1], payment_reference=line.get("payment_ref") or line.get("ref"),
            move_id=move[0], account_id=account[0], journal_id=journal[0], reconciliation_status="reconciled" if matched else "open",
        ))
    return result


def _date_diff(a: str, b: str) -> int | None:
    try:
        return abs((datetime.strptime(a, "%Y-%m-%d") - datetime.strptime(b, "%Y-%m-%d")).days)
    except ValueError:
        return None


@dataclass
class Candidate:
    bank_index: int
    odoo_index: int
    status: str
    confidence: int
    reason: str
    compared: dict[str, Any]
    amount_mismatch: bool = False


def _candidate(bank: BankStatementLine, odoo: OdooBankLedgerLine, tolerance_days: int) -> Candidate | None:
    bank_amount = round(bank.credit - bank.debit, 2)
    odoo_amount = round(odoo.debit - odoo.credit, 2)
    amount_diff = round(bank_amount - odoo_amount, 2)
    amount_same = abs(amount_diff) < 0.01
    days = _date_diff(bank.transaction_date, odoo.move_date)
    date_close = days is not None and days <= tolerance_days
    ref_similarity = text_similarity(bank.reference, odoo.payment_reference, odoo.journal_entry_number)
    desc_similarity = text_similarity(" ".join([bank.description, bank.counterparty or ""]), odoo.label, odoo.partner, odoo.payment_reference)
    best_text = max(ref_similarity, desc_similarity)
    compared = {"bank_amount": bank_amount, "odoo_amount": odoo_amount, "amount_difference": amount_diff, "date_difference_days": days, "reference_similarity": round(ref_similarity, 3), "description_similarity": round(desc_similarity, 3)}
    if amount_same and days == 0 and (ref_similarity >= 0.82 or desc_similarity >= 0.76):
        return Candidate(-1, -1, "exact_match", 98, "Same amount, same date, and matching reference/description.", compared)
    if amount_same and date_close and best_text >= 0.70:
        return Candidate(-1, -1, "strong_match", 88, "Same amount, date within tolerance, and high reference/description similarity.", compared)
    if amount_same and date_close and (best_text >= 0.42 or ref_similarity >= 0.35):
        return Candidate(-1, -1, "possible_match", 68, "Same amount and date within tolerance with partial narrative/reference similarity.", compared)
    if not amount_same and date_close and (best_text >= 0.62 or ref_similarity >= 0.50):
        confidence = 74 if abs(amount_diff) <= 10 else 61
        return Candidate(-1, -1, "amount_mismatch", confidence, "Reference/date/description suggest the same transaction but amount differs.", compared, True)
    return None


def suggested_bank_action(line: BankStatementLine) -> str:
    text = _norm(f"{line.description} {line.counterparty or ''}")
    if any(token in text for token in ["fee", "charge", "رسوم", "عموله", "عمولة"]):
        return "create bank fee"
    if line.credit > 0:
        return "create payment"
    if line.debit > 0:
        return "import to Odoo"
    return "investigate"


def reconcile_bank_to_odoo(bank_lines: list[BankStatementLine], odoo_lines: list[OdooBankLedgerLine], tolerance_days: int = 3) -> BankReconciliationReport:
    if tolerance_days < 0:
        raise ValueError("date_tolerance_days must be zero or greater.")
    candidates: list[Candidate] = []
    by_bank: dict[int, list[Candidate]] = {}
    by_odoo: dict[int, list[Candidate]] = {}
    for bi, bank in enumerate(bank_lines):
        for oi, odoo in enumerate(odoo_lines):
            cand = _candidate(bank, odoo, tolerance_days)
            if not cand:
                continue
            cand.bank_index = bi
            cand.odoo_index = oi
            candidates.append(cand)
            by_bank.setdefault(bi, []).append(cand)
            by_odoo.setdefault(oi, []).append(cand)
    candidates.sort(key=lambda c: (c.amount_mismatch, -c.confidence, c.compared.get("date_difference_days") or 999))
    used_bank: set[int] = set()
    used_odoo: set[int] = set()
    matched: list[MatchLine] = []
    mismatches: list[AmountMismatch] = []
    for cand in candidates:
        if cand.bank_index in used_bank or cand.odoo_index in used_odoo:
            continue
        bank = bank_lines[cand.bank_index]
        odoo = odoo_lines[cand.odoo_index]
        used_bank.add(cand.bank_index)
        used_odoo.add(cand.odoo_index)
        if cand.amount_mismatch:
            mismatches.append(AmountMismatch(bank_line=bank, odoo_line=odoo, amount_difference=cand.compared["amount_difference"], likely_reason="Bank fees, FX, partial settlement, discount, or posting amount differs from bank statement.", confidence_score=cand.confidence, compared_fields=cand.compared))
        else:
            matched.append(MatchLine(bank_line=bank, odoo_line=odoo, match_status=cand.status, confidence_score=cand.confidence, match_reason=cand.reason, compared_fields=cand.compared))
    duplicates: list[DuplicateRisk] = []
    for bi, bank_candidates in by_bank.items():
        viable = [c for c in bank_candidates if not c.amount_mismatch and c.confidence >= 60]
        if len(viable) > 1:
            duplicates.append(DuplicateRisk(bank_line=bank_lines[bi], possible_odoo_matches=[odoo_lines[c.odoo_index] for c in viable[:5]], reason="Multiple Odoo ledger lines meet amount/date/reference matching rules for this bank line."))
    for oi, odoo_candidates in by_odoo.items():
        viable = [c for c in odoo_candidates if not c.amount_mismatch and c.confidence >= 60]
        if len(viable) > 1:
            duplicates.append(DuplicateRisk(odoo_line=odoo_lines[oi], possible_bank_matches=[bank_lines[c.bank_index] for c in viable[:5]], reason="Multiple bank statement lines can match the same Odoo ledger line."))
    unmatched = [UnmatchedBankLine(bank_line=line, suggested_action=suggested_bank_action(line), reason="No reliable posted Odoo bank ledger match found within amount/date/reference rules.") for i, line in enumerate(bank_lines) if i not in used_bank]
    missing = [MissingOdooLine(odoo_line=line, suggested_action="check posting date" if line.reconciliation_status == "open" else "investigate", reason="Posted Odoo bank ledger line was not found in the uploaded bank statement.") for i, line in enumerate(odoo_lines) if i not in used_odoo]
    exact = sum(1 for m in matched if m.match_status == "exact_match")
    strong = sum(1 for m in matched if m.match_status == "strong_match")
    possible = sum(1 for m in matched if m.match_status == "possible_match")
    bank_debit = round(sum(l.debit for l in bank_lines), 2)
    bank_credit = round(sum(l.credit for l in bank_lines), 2)
    odoo_debit = round(sum(l.debit for l in odoo_lines), 2)
    odoo_credit = round(sum(l.credit for l in odoo_lines), 2)
    summary = ReconciliationSummary(total_bank_statement_lines=len(bank_lines), total_odoo_ledger_lines=len(odoo_lines), exact_matches_count=exact, strong_matches_count=strong, possible_matches_count=possible, unmatched_bank_lines_count=len(unmatched), missing_in_bank_statement_count=len(missing), amount_mismatch_count=len(mismatches), duplicate_risk_count=len(duplicates), bank_total_debit=bank_debit, bank_total_credit=bank_credit, odoo_total_debit=odoo_debit, odoo_total_credit=odoo_credit, net_difference=round((bank_credit - bank_debit) - (odoo_debit - odoo_credit), 2))
    logger.info("Bank reconciliation report generated", extra={"bank_lines": len(bank_lines), "odoo_lines": len(odoo_lines), "exact": exact, "strong": strong, "possible": possible})
    return BankReconciliationReport(summary=summary, matched_lines=matched, unmatched_bank_lines=unmatched, missing_in_bank_statement=missing, amount_mismatches=mismatches, duplicate_risks=duplicates)
