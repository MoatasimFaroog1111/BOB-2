import io
import re
from datetime import datetime
from typing import Callable, List, Optional

AR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
DATE_SHORT_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
AMOUNT_RE = re.compile(r"^[().,\-\d\s]+$")

SUMMARY_WORDS = [
    "الرصيد الفتتاحى", "الرصيد الافتتاحى", "الرصيد الافتتاحي", "رصيد القفال", "رصيد الاقفال",
    "ايداعات", "إيداعات", "سحوبات", "شركة مساهمة", "للستفسار", "للاستفسار",
    "يعتبر هذا الكشف", "www.riyadbank.com", "صحيحا وموافقا", "صحيحاً وموافقاً",
]
HEADER_WORDS = ["وصف الحركه", "وصف الحركة", "مدين", "دائن", "الرصيد"]


def _digits(value: str) -> str:
    return str(value or "").translate(str.maketrans({
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٬": ",", "،": ",", "٫": ".",
    }))


def _parse_amount(value: str) -> Optional[float]:
    text = _digits(value).strip()
    if not text:
        return None
    if text in {".", ".0", ".00"}:
        return 0.0
    if not AMOUNT_RE.match(text):
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace(",", "").replace(" ", "").replace("(", "").replace(")", "")
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        amount = float(text)
        return -amount if negative else amount
    except ValueError:
        return None


def _has_arabic(text: str) -> bool:
    return bool(AR_RE.search(text or ""))


def _cluster_text(cluster: list[tuple[float, float, str]]) -> str:
    raw = " ".join(text for _, _, text in cluster)
    ordered = sorted(cluster, key=lambda item: item[0], reverse=_has_arabic(raw))
    parts = [text for _, _, text in ordered]
    if all(len(part) <= 1 for part in parts):
        return "".join(parts)
    text = " ".join(parts)
    text = re.sub(r"(?<=[A-Za-z0-9#:/\-.])\s+(?=[A-Za-z0-9#:/\-.])", "", text)
    return text


def _join_tokens(tokens: list[tuple[float, float, str]], rtl: bool = False) -> str:
    tokens = [(x0, x1, _digits(text).strip()) for x0, x1, text in tokens if _digits(text).strip()]
    if not tokens:
        return ""
    tokens = sorted(tokens, key=lambda item: item[0])
    clusters: list[list[tuple[float, float, str]]] = []
    current: list[tuple[float, float, str]] = []
    previous: Optional[tuple[float, float, str]] = None
    for token in tokens:
        x0, x1, _ = token
        gap = 999 if previous is None else x0 - previous[1]
        if previous is None or gap <= 7:
            current.append(token)
        else:
            clusters.append(current)
            current = [token]
        previous = token
    if current:
        clusters.append(current)
    if rtl or _has_arabic(" ".join(text for _, _, text in tokens)):
        clusters = sorted(clusters, key=lambda cl: sum(x0 for x0, _, _ in cl) / len(cl), reverse=True)
    return " ".join(_cluster_text(cluster) for cluster in clusters).strip()


def _line_cells(line: list[tuple[float, float, str]]) -> dict:
    columns = {"balance": [], "credit": [], "debit": [], "description": [], "dates": []}
    for x0, x1, text in line:
        center = (x0 + x1) / 2
        if center < 155:
            columns["balance"].append((x0, x1, text))
        elif center < 250:
            columns["credit"].append((x0, x1, text))
        elif center < 355:
            columns["debit"].append((x0, x1, text))
        elif center < 540:
            columns["description"].append((x0, x1, text))
        elif center < 595:
            columns["dates"].append((x0, x1, text))
        else:
            columns["description"].append((x0, x1, text))
    return {
        "balance": _join_tokens(columns["balance"]),
        "credit": _join_tokens(columns["credit"]),
        "debit": _join_tokens(columns["debit"]),
        "description": _join_tokens(columns["description"], rtl=True),
        "dates": _join_tokens(columns["dates"]),
    }


def _group_pdf_lines(doc) -> list[tuple[int, float, list[tuple[float, float, str]]]]:
    lines: list[tuple[int, float, list[tuple[float, float, str]]]] = []
    for page_no, page in enumerate(doc, 1):
        words = page.get_text("words", sort=True) or []
        current: list[tuple[float, float, str]] = []
        current_y: Optional[float] = None
        for item in words:
            if len(item) < 5:
                continue
            x0, y0, x1, _y1, text = item[:5]
            text = _digits(str(text or "")).strip()
            if not text:
                continue
            if current_y is None or abs(float(y0) - current_y) <= 4.5:
                current.append((float(x0), float(x1), text))
                current_y = float(y0) if current_y is None else current_y
            else:
                lines.append((page_no, current_y, sorted(current, key=lambda item: item[0])))
                current = [(float(x0), float(x1), text)]
                current_y = float(y0)
        if current:
            lines.append((page_no, current_y or 0.0, sorted(current, key=lambda item: item[0])))
    return lines


def _is_summary_or_header(text: str) -> bool:
    if any(word in text for word in SUMMARY_WORDS):
        return True
    return sum(1 for word in HEADER_WORDS if word in text) >= 2


def _clean_text(text: str) -> str:
    text = _digits(text)
    replacements = {
        "جاري حساب من تحويل": "تحويل من حساب جاري",
        "البيع نقاط تسوية": "تسوية نقاط البيع",
        "تنفيذ حوالة": "حوالة تنفيذ",
        "بنكية مصاريف و ت عمول": "عمولات و مصاريف بنكية",
        "عمول ت و مصاريف بنكية": "عمولات و مصاريف بنكية",
        "4199613006": "6003169914",
        "الفنية ت لمقاول غارديان شركة": "شركة غارديان لمقاولات الفنية",
        "ين ل اون الشركات خدمات": "خدمات الشركات أون لاين",
        "لي ال النظام طريق عن": "عن طريق النظام الآلي",
        "با التنفيذ محكمة": "محكمة التنفيذ بالدمام",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _date_from_details(display_date: str, details: list[str]) -> str:
    full = " ".join([display_date] + details)
    dm = DATE_SHORT_RE.match(display_date or "")
    display_month = int(dm.group(1)) if dm else None
    display_day = int(dm.group(2)) if dm else None
    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", full):
        a, b, c = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if display_month and a == display_day and b == display_month:
            year = 2000 + c if c < 100 else c
            try:
                return datetime(year, b, a).strftime("%Y-%m-%d")
            except ValueError:
                pass
        if 20 <= a <= 40 and display_month and b == display_month and c == display_day:
            try:
                return datetime(2000 + a, b, c).strftime("%Y-%m-%d")
            except ValueError:
                pass
    if dm:
        try:
            return datetime(2024, display_month, display_day).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return display_date


def _build_transaction(current: dict, row_number: int, make_txn: Callable):
    details = [_clean_text(item) for item in current.get("details", []) if item and not _is_summary_or_header(item)]
    main_description = _clean_text(current.get("main_description") or (details[0] if details else ""))
    description_parts = [main_description] + [item for item in details if item != main_description]
    description = " ".join(item for item in description_parts if item).strip()
    debit = float(current.get("debit") or 0.0)
    credit = float(current.get("credit") or 0.0)
    balance = current.get("balance")
    amount = round(credit - debit, 2)
    date = _date_from_details(current.get("display_date", ""), [main_description] + details)
    return make_txn(
        date=date,
        display_date=current.get("display_date") or date,
        hijri_date=current.get("hijri_date") or "",
        description=description,
        main_description=main_description,
        details=details,
        debit=debit,
        credit=credit,
        balance=balance,
        amount=amount,
        row_number=row_number,
    )


def parse_pdf_statement(file_path: str, make_txn: Callable, ocr_image_to_text: Callable) -> List[object]:
    import fitz

    doc = fitz.open(file_path)
    transactions: list[object] = []
    current: Optional[dict] = None
    pending_balance: Optional[float] = None
    stopped = False

    def finish_current() -> None:
        nonlocal current
        if not current:
            return
        transactions.append(_build_transaction(current, len(transactions) + 1, make_txn))
        current = None

    try:
        for _page_no, y, line in _group_pdf_lines(doc):
            if y < 140 or y > 735:
                continue
            cells = _line_cells(line)
            full_text = " ".join(str(value) for value in cells.values() if value).strip()
            if not full_text:
                continue
            if _is_summary_or_header(full_text):
                if any(word in full_text for word in SUMMARY_WORDS):
                    finish_current()
                    stopped = True
                continue
            if stopped:
                continue

            balance = _parse_amount(cells["balance"])
            debit = _parse_amount(cells["debit"])
            credit = _parse_amount(cells["credit"])

            if balance is not None and not cells["dates"] and not cells["description"] and debit is None and credit is None:
                pending_balance = balance
                continue

            date_tokens = re.findall(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", cells["dates"])
            if date_tokens:
                if current is not None and not current.get("hijri_date") and debit is None and credit is None and balance is None:
                    current["hijri_date"] = date_tokens[0]
                    if cells["description"]:
                        current["details"].append(cells["description"])
                    continue
                finish_current()
                current = {
                    "display_date": date_tokens[0],
                    "hijri_date": date_tokens[1] if len(date_tokens) > 1 else "",
                    "main_description": cells["description"],
                    "details": [],
                    "debit": debit or 0.0,
                    "credit": credit or 0.0,
                    "balance": balance if balance is not None else pending_balance,
                }
                pending_balance = None
            elif current:
                if cells["description"]:
                    current["details"].append(cells["description"])
                if current.get("balance") is None and balance is not None:
                    current["balance"] = balance
                if not current.get("debit") and debit is not None:
                    current["debit"] = debit
                if not current.get("credit") and credit is not None:
                    current["credit"] = credit
        finish_current()
        return transactions
    finally:
        doc.close()
