import io
import re
from datetime import datetime
from typing import Callable, List, Optional

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5,
    "يونيو": 6, "يونيه": 6, "يوليو": 7, "يوليه": 7, "أغسطس": 8, "اغسطس": 8,
    "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}
_MONTH_PATTERN = "|".join(sorted((re.escape(k) for k in _MONTHS), key=len, reverse=True))
_DATE_RE = re.compile(
    rf"(\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}|\d{{8}}|\d{{1,2}}\s+(?:{_MONTH_PATTERN})\s*,?\s*\d{{2,4}}|(?:{_MONTH_PATTERN})\s+\d{{1,2}},?\s+\d{{2,4}})",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"(?<![\dA-Za-z])(" 
    r"\(?-?\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,4})?\)?"
    r"|\(?-?\d+\.\d{1,4}\)?"
    r"|\(?-?\d{1,9}\)?"
    r")(?![\dA-Za-z])"
)

_SKIP_WORDS = [
    "opening balance", "closing balance", "available balance", "running balance",
    "statement summary", "total debit", "total credit", "total deposits", "total withdrawals",
    "account number", "iban", "swift", "customer number", "page ",
    "الرصيد الافتتاحي", "الرصيد الختامي", "الرصيد المتاح", "رصيد افتتاحي", "رصيد ختامي",
    "الرصيد المرحل", "إجمالي", "اجمالي", "مجموع", "ملخص", "رقم الحساب", "ايبان", "آيبان",
]
_DEBIT_WORDS = ["debit", "withdrawal", "paid out", "dr", "سحب", "مدين", "خصم", "دفع"]
_CREDIT_WORDS = ["credit", "deposit", "paid in", "cr", "إيداع", "ايداع", "دائن", "وارد"]
_MONEY_CONTEXT = [
    "sar", "sr", "riyal", "riyals", "ر.س", "ريال", "amount", "debit", "credit", "balance",
    "مبلغ", "مدين", "دائن", "سحب", "خصم", "إيداع", "ايداع", "الرصيد",
]


def _digits(value: str) -> str:
    return str(value or "").translate(str.maketrans({
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٬": ",", "،": ",", "٫": ".",
    }))


def _expand_year(year: int) -> int:
    if year < 100:
        return 2000 + year if year <= 69 else 1900 + year
    return year


def _month_number(value: str) -> Optional[int]:
    return _MONTHS.get(value.strip().lower())


def _date(text: str) -> str:
    text = _digits(text).strip()
    if not text:
        return ""

    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if m:
        first, second, year = int(m.group(1)), int(m.group(2)), _expand_year(int(m.group(3)))
        day, month = (second, first) if second > 12 else (first, second)
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m = re.search(rf"(\d{{1,2}})\s+({_MONTH_PATTERN})\s*,?\s*(\d{{2,4}})", text, re.IGNORECASE)
    if m:
        month = _month_number(m.group(2))
        if month:
            try:
                return datetime(_expand_year(int(m.group(3))), month, int(m.group(1))).strftime("%Y-%m-%d")
            except ValueError:
                pass

    m = re.search(rf"({_MONTH_PATTERN})\s+(\d{{1,2}}),?\s+(\d{{2,4}})", text, re.IGNORECASE)
    if m:
        month = _month_number(m.group(1))
        if month:
            try:
                return datetime(_expand_year(int(m.group(3))), month, int(m.group(2))).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return ""


def _number(token: str) -> Optional[float]:
    raw = _digits(token).strip()
    neg = raw.startswith("(") and raw.endswith(")")
    clean = re.sub(r"[^\d.,()\-]", "", raw).replace(",", "").replace(" ", "").replace("(", "").replace(")", "")
    if not clean or clean in {"-", ".", "-."}:
        return None
    try:
        value = float(clean)
        return -value if neg and value > 0 else value
    except ValueError:
        return None


def _skip(text: str) -> bool:
    low = _digits(text).lower()
    return any(word in low for word in _SKIP_WORDS)


def _has_money_context(text: str) -> bool:
    low = text.lower()
    return any(word in low for word in _MONEY_CONTEXT)


def _amounts(row_text: str) -> list[dict]:
    text = _digits(row_text)
    context = _has_money_context(text)
    out = []
    for m in _MONEY_RE.finditer(text):
        token = m.group(1)
        value = _number(token)
        if value is None or value == 0:
            continue
        if float(value).is_integer() and 1900 <= abs(value) <= 2100:
            continue
        digits_only = re.sub(r"\D", "", token)
        has_money_shape = any(ch in token for ch in [".", ",", " ", "(", ")", "-"])
        if len(digits_only) >= 7 and not has_money_shape and not context:
            continue
        if len(digits_only) <= 1 and not has_money_shape and not context:
            continue
        out.append({"token": token, "amount": value, "start": m.start(1), "end": m.end(1)})
    return out


def _date_token(row_text: str, cells: List[str]) -> tuple[str, str]:
    for cell in cells:
        d = _date(str(cell))
        if d:
            found = _DATE_RE.search(_digits(str(cell)))
            return d, found.group(1) if found else str(cell)
    found = _DATE_RE.search(_digits(row_text))
    if found:
        return _date(found.group(1)), found.group(1)
    return "", ""


def _choose_amount(candidates: list[dict], row_text: str) -> Optional[dict]:
    if not candidates:
        return None
    # Many bank PDFs end with running balance, so use the first movement amount.
    selected = dict(candidates[0])
    low = row_text.lower()
    if any(w in low for w in _DEBIT_WORDS) and not any(w in low for w in _CREDIT_WORDS):
        selected["amount"] = -abs(float(selected["amount"]))
    elif any(w in low for w in _CREDIT_WORDS) and not any(w in low for w in _DEBIT_WORDS):
        selected["amount"] = abs(float(selected["amount"]))
    return selected


def _txn_from_row(cells: List[str], row_number: int, make_txn: Callable) -> Optional[object]:
    row_text = " ".join(str(c).strip() for c in cells if str(c).strip())
    if not row_text or _skip(row_text):
        return None
    txn_date, d_token = _date_token(row_text, cells)
    if not txn_date:
        return None
    selected = _choose_amount(_amounts(row_text), row_text)
    if not selected:
        return None
    desc = _digits(row_text).replace(d_token, " ", 1).replace(selected["token"], " ", 1)
    desc = re.sub(r"\b(SAR|SR|RIYAL|RIYALS|ر\.س|ريال|رس)\b", " ", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip(" -|,؛:.")
    if not desc or _skip(desc):
        return None
    return make_txn(date=txn_date, description=desc, amount=round(float(selected["amount"]), 2), row_number=row_number)


def _from_rows(rows: List[List[str]], make_txn: Callable) -> List[object]:
    txns = []
    for i, row in enumerate(rows, start=1):
        txn = _txn_from_row(row, i, make_txn)
        if txn:
            txns.append(txn)
    return txns


def _fitz_tables(doc) -> List[List[str]]:
    rows = []
    for page in doc:
        finder = getattr(page, "find_tables", None)
        if not finder:
            continue
        try:
            tables = finder()
            for table in getattr(tables, "tables", []) or []:
                for row in table.extract() or []:
                    cells = [str(c).strip() if c is not None else "" for c in row]
                    if any(cells):
                        rows.append(cells)
        except Exception:
            continue
    return rows


def _word_rows(doc) -> List[List[str]]:
    rows = []
    for page in doc:
        words = page.get_text("words", sort=True) or []
        current_y = None
        line = []
        for item in words:
            if len(item) < 5:
                continue
            x0, y0, x1, y1, text = item[:5]
            text = _digits(str(text or "")).strip()
            if not text:
                continue
            if current_y is None or abs(float(y0) - current_y) <= 4.5:
                line.append((float(x0), float(x1), text))
                current_y = float(y0) if current_y is None else current_y
            else:
                rows.append(_cells_from_line(line))
                line = [(float(x0), float(x1), text)]
                current_y = float(y0)
        if line:
            rows.append(_cells_from_line(line))
    return [r for r in rows if r]


def _cells_from_line(line) -> List[str]:
    line = sorted(line, key=lambda x: x[0])
    if not line:
        return []
    positive_gaps = [line[i][0] - line[i - 1][1] for i in range(1, len(line)) if line[i][0] - line[i - 1][1] > 0]
    median_gap = (sorted(positive_gaps) or [4.0])[len(positive_gaps) // 2 if positive_gaps else 0]
    big_gap = max(10.0, min(45.0, median_gap * 3))
    cells = []
    cur = [line[0][2]]
    prev = line[0]
    for item in line[1:]:
        if item[0] - prev[1] > big_gap:
            cells.append(" ".join(cur))
            cur = [item[2]]
        else:
            cur.append(item[2])
        prev = item
    cells.append(" ".join(cur))
    return cells


def _text_rows(text: str) -> List[List[str]]:
    rows = []
    for line in text.splitlines():
        line = _digits(line).strip()
        if not line:
            continue
        rows.append([p.strip() for p in re.split(r"\s{2,}|\t|\|", line) if p.strip()] or [line])
    return rows


def parse_pdf_statement(file_path: str, make_txn: Callable, ocr_image_to_text: Callable) -> List[object]:
    import fitz
    from PIL import Image

    doc = fitz.open(file_path)
    try:
        for rows in (_fitz_tables(doc), _word_rows(doc)):
            txns = _from_rows(rows, make_txn)
            if txns:
                return txns
        text = "\n".join((p.get_text("text") or "") for p in doc)
        txns = _from_rows(_text_rows(text), make_txn)
        if txns:
            return txns
        ocr_text = []
        for i in range(min(len(doc), 25)):
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_text.append(ocr_image_to_text(image))
        return _from_rows(_text_rows("\n".join(ocr_text)), make_txn)
    finally:
        doc.close()
