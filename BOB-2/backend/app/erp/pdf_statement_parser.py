import io
import re
from datetime import datetime
from typing import Callable, List, Optional

_DATE_RE = re.compile(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{8})")
_MONEY_RE = re.compile(r"(?<!\d)(\(?-?\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,2})?\)?|\(?-?\d+\.\d{1,4}\)?)(?!\d)")

_SKIP_WORDS = [
    "opening balance", "closing balance", "available balance", "running balance",
    "statement summary", "total debit", "total credit", "account number", "iban",
    "الرصيد الافتتاحي", "الرصيد الختامي", "الرصيد المتاح", "إجمالي", "اجمالي", "مجموع", "رقم الحساب", "ايبان",
]
_DEBIT_WORDS = ["debit", "withdrawal", "paid out", "dr", "سحب", "مدين", "خصم", "دفع"]
_CREDIT_WORDS = ["credit", "deposit", "paid in", "cr", "إيداع", "ايداع", "دائن", "وارد"]


def _digits(value: str) -> str:
    return str(value or "").translate(str.maketrans({
        "٠":"0","١":"1","٢":"2","٣":"3","٤":"4","٥":"5","٦":"6","٧":"7","٨":"8","٩":"9",
        "۰":"0","۱":"1","۲":"2","۳":"3","۴":"4","۵":"5","۶":"6","۷":"7","۸":"8","۹":"9",
        "٬":",","،":",","٫":".",
    }))


def _date(text: str) -> str:
    text = _digits(text)
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day, month = (b, a) if b > 12 else (a, b)
        try:
            return datetime(y, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _number(token: str) -> Optional[float]:
    raw = _digits(token).strip()
    neg = raw.startswith("(") and raw.endswith(")")
    clean = re.sub(r"[^\d.,()\-]", "", raw).replace(",", "").replace("(", "").replace(")", "")
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


def _amounts(row_text: str) -> list[dict]:
    text = _digits(row_text)
    out = []
    for m in _MONEY_RE.finditer(text):
        token = m.group(1)
        value = _number(token)
        if value is None or value == 0:
            continue
        if float(value).is_integer() and 1900 <= abs(value) <= 2100:
            continue
        out.append({"token": token, "amount": value})
    return out


def _txn_from_row(cells: List[str], row_number: int, make_txn: Callable) -> Optional[object]:
    row_text = " ".join(str(c).strip() for c in cells if str(c).strip())
    if not row_text or _skip(row_text):
        return None
    txn_date = ""
    date_token = ""
    for cell in cells:
        txn_date = _date(str(cell))
        if txn_date:
            found = _DATE_RE.search(_digits(str(cell)))
            date_token = found.group(1) if found else str(cell)
            break
    if not txn_date:
        return None
    candidates = _amounts(row_text)
    if not candidates:
        return None
    selected = dict(candidates[0])
    low = row_text.lower()
    if any(w in low for w in _DEBIT_WORDS) and not any(w in low for w in _CREDIT_WORDS):
        selected["amount"] = -abs(float(selected["amount"]))
    elif any(w in low for w in _CREDIT_WORDS) and not any(w in low for w in _DEBIT_WORDS):
        selected["amount"] = abs(float(selected["amount"]))
    desc = _digits(row_text).replace(date_token, " ", 1).replace(selected["token"], " ", 1)
    desc = re.sub(r"\b(SAR|SR|RIYAL|ر\.س|ريال|رس)\b", " ", desc, flags=re.I)
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
            if current_y is None or abs(float(y0) - current_y) <= 3.5:
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
    gaps = [line[i][0] - line[i-1][1] for i in range(1, len(line))]
    big_gap = max(10.0, min(40.0, (sorted([g for g in gaps if g > 0]) or [4.0])[len([g for g in gaps if g > 0]) // 2] * 3))
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
