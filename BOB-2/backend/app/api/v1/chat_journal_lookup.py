import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.erp import ChatSpreadsheetRequest, chat_spreadsheet as legacy_chat_spreadsheet
from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value

router = APIRouter()

ENTRY_REFERENCE_PATTERN = re.compile(
    r"\b([A-Z][A-Z0-9]{1,12}\s*/\s*[0-9]{4}\s*(?:/\s*[0-9]{1,2})?\s*/\s*[0-9]{3,8})\b",
    re.IGNORECASE,
)

ENTRY_ID_PATTERN = re.compile(
    r"(?:"
    r"move\s*id|move_id|journal\s*entry\s*(?:id|number|no\.?|#)?|entry\s*(?:id|number|no\.?|#)?|"
    r"رقم\s*(?:القيد|قيد)|معرف\s*(?:القيد|قيد)|قيد\s*رقم"
    r")\s*[:#\-–—]?\s*([0-9٠-٩]{2,10})",
    re.IGNORECASE,
)

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _normalize_digits(value: str) -> str:
    return (value or "").translate(ARABIC_DIGITS)


def _normalize_move_reference(value: str) -> str:
    normalized = _normalize_digits(value or "").upper()
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.strip(".,;:()[]{}<>\"'،؛")


def _collect_payload_text(payload: ChatSpreadsheetRequest) -> str:
    pieces: list[str] = [payload.prompt or ""]
    for sheet in payload.sheets or []:
        pieces.append(sheet.name or "")
        for row in sheet.gridData or []:
            pieces.append(" ".join(str(cell or "") for cell in row))
    return "\n".join(pieces)


def extract_journal_entry_numbers(text: str) -> tuple[list[str], list[int]]:
    normalized_text = _normalize_digits(text or "")

    references: list[str] = []
    for match in ENTRY_REFERENCE_PATTERN.finditer(normalized_text):
        ref = _normalize_move_reference(match.group(1))
        if ref and ref not in references:
            references.append(ref)

    move_ids: list[int] = []
    for match in ENTRY_ID_PATTERN.finditer(normalized_text):
        raw_number = _normalize_digits(match.group(1)).strip()
        # If the user writes فقط رقم التسلسل مثل 001003 بعد عبارة رقم القيد، search it
        # as a textual Odoo move name fragment as well as a possible internal move id.
        if len(raw_number) >= 4 and raw_number not in references:
            references.append(raw_number)
        try:
            move_id = int(raw_number)
        except Exception:
            continue
        if move_id not in move_ids:
            move_ids.append(move_id)

    return references, move_ids


def _is_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _read_saved_erp(db_session: Session):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True,  # noqa: E712 - keep existing project style
    ).first()

    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to decrypt connection credentials.")

    erp = get_erp_provider(
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=username,
        password=password,
    )
    return conn, erp, username


def _resolve_effective_company_id(erp, username: str, requested_company_id: int | None) -> int | None:
    if requested_company_id:
        return requested_company_id
    try:
        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1},
        )
        if users and users[0].get("company_id"):
            company = users[0]["company_id"]
            if isinstance(company, list) and company:
                return int(company[0])
    except Exception:
        return None
    return None


def _dedupe_moves(moves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    deduped: list[dict[str, Any]] = []
    for move in moves:
        move_id = move.get("id")
        if not isinstance(move_id, int) or move_id in seen:
            continue
        seen.add(move_id)
        deduped.append(move)
    return deduped


def _search_moves_by_reference(erp, ref: str, company_id: int | None, fields: list[str]) -> list[dict[str, Any]]:
    searches = [
        ("name", "=", ref),
        ("ref", "=", ref),
        ("payment_reference", "=", ref),
        ("name", "ilike", ref),
        ("ref", "ilike", ref),
        ("payment_reference", "ilike", ref),
    ]

    found: list[dict[str, Any]] = []
    for field, operator, value in searches:
        domain: list[Any] = [[field, operator, value]]
        if company_id:
            domain.append(["company_id", "=", company_id])
        try:
            moves = erp.execute_kw(
                "account.move",
                "search_read",
                [domain],
                {"fields": fields, "order": "date desc, id desc", "limit": 10},
            )
            found.extend(moves or [])
        except Exception:
            continue
    return _dedupe_moves(found)


def _search_moves_by_ids(erp, move_ids: list[int], company_id: int | None, fields: list[str]) -> list[dict[str, Any]]:
    if not move_ids:
        return []
    domain: list[Any] = [["id", "in", move_ids]]
    if company_id:
        domain.append(["company_id", "=", company_id])
    try:
        return erp.execute_kw(
            "account.move",
            "search_read",
            [domain],
            {"fields": fields, "order": "date desc, id desc", "limit": max(len(move_ids), 1)},
        ) or []
    except Exception:
        return []


def _read_move_lines(erp, line_ids: list[int]) -> list[dict[str, Any]]:
    if not line_ids:
        return []
    try:
        return erp.execute_kw(
            "account.move.line",
            "search_read",
            [[["id", "in", line_ids]]],
            {
                "fields": ["id", "move_id", "account_id", "name", "debit", "credit", "partner_id"],
                "order": "id asc",
                "limit": len(line_ids),
            },
        ) or []
    except Exception:
        return []


def _many2one_name(value: Any) -> str:
    if isinstance(value, list) and len(value) > 1:
        return str(value[1] or "")
    if isinstance(value, tuple) and len(value) > 1:
        return str(value[1] or "")
    return ""


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, list) and value:
        try:
            return int(value[0])
        except Exception:
            return None
    if isinstance(value, tuple) and value:
        try:
            return int(value[0])
        except Exception:
            return None
    if isinstance(value, int):
        return value
    return None


def _account_code(account_label: str) -> str:
    match = re.match(r"^\s*([0-9][0-9.\-]*)", account_label or "")
    return match.group(1) if match else ""


def _build_grid_from_moves(conn, moves: list[dict[str, Any]], move_lines: list[dict[str, Any]], arabic: bool) -> list[list[str]]:
    if arabic:
        header = ["رقم القيد", "التاريخ", "الدفتر", "الشريك", "رمز الحساب", "اسم الحساب", "البيان", "مدين", "دائن", "المرجع", "رابط Odoo"]
    else:
        header = ["Entry Number", "Date", "Journal", "Partner", "Account Code", "Account Name", "Label", "Debit", "Credit", "Reference", "Odoo URL"]

    base_url = (conn.base_url or "").rstrip("/")
    rows: list[list[str]] = [header]

    lines_by_move: dict[int, list[dict[str, Any]]] = {}
    for line in move_lines:
        move_id = _many2one_id(line.get("move_id"))
        if move_id:
            lines_by_move.setdefault(move_id, []).append(line)

    for move in moves:
        move_id = move.get("id")
        entry_name = str(move.get("name") or "")
        move_date = str(move.get("date") or move.get("invoice_date") or "")
        journal_name = _many2one_name(move.get("journal_id"))
        partner_name = _many2one_name(move.get("partner_id"))
        ref = str(move.get("ref") or move.get("payment_reference") or "")
        odoo_url = f"{base_url}/web#id={move_id}&model=account.move&view_type=form" if move_id and base_url else ""
        lines = lines_by_move.get(int(move_id or 0), [])

        if not lines:
            rows.append([
                entry_name,
                move_date,
                journal_name,
                partner_name,
                "",
                "",
                ref,
                "",
                "",
                ref,
                odoo_url,
            ])
            continue

        for line in lines:
            account_name = _many2one_name(line.get("account_id"))
            rows.append([
                entry_name,
                move_date,
                journal_name,
                _many2one_name(line.get("partner_id")) or partner_name,
                _account_code(account_name),
                account_name,
                str(line.get("name") or ""),
                str(float(line.get("debit") or 0.0)) if float(line.get("debit") or 0.0) else "",
                str(float(line.get("credit") or 0.0)) if float(line.get("credit") or 0.0) else "",
                ref,
                odoo_url,
            ])

    return rows


@router.post("/chat-spreadsheet")
def chat_spreadsheet_with_odoo_entry_lookup(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    collected_text = _collect_payload_text(payload)
    references, move_ids = extract_journal_entry_numbers(collected_text)

    if not references and not move_ids:
        return legacy_chat_spreadsheet(payload=payload, db_session=db_session)

    arabic = _is_arabic(payload.prompt)

    try:
        conn, erp, username = _read_saved_erp(db_session)
        company_id = _resolve_effective_company_id(erp, username, payload.company_id)
    except HTTPException as exc:
        return {
            "message": "لم أتمكن من جلب القيود لأن اتصال Odoo غير مفعّل أو غير مكتمل." if arabic else "Could not fetch entries because the Odoo connection is not active or complete.",
            "grid_data": None,
            "detected_entry_numbers": references,
            "detected_move_ids": move_ids,
            "error": exc.detail,
        }

    move_fields = [
        "id",
        "name",
        "ref",
        "date",
        "invoice_date",
        "amount_total",
        "journal_id",
        "partner_id",
        "state",
        "move_type",
        "line_ids",
        "payment_reference",
        "company_id",
    ]

    moves: list[dict[str, Any]] = []
    for ref in references:
        moves.extend(_search_moves_by_reference(erp, ref, company_id, move_fields))
    moves.extend(_search_moves_by_ids(erp, move_ids, company_id, move_fields))
    moves = _dedupe_moves(moves)

    if not moves:
        detected = references + [str(mid) for mid in move_ids]
        return {
            "message": (
                f"قرأت أرقام القيود من البيانات ({', '.join(detected)})، لكن لم أجد قيودًا مطابقة في Odoo."
                if arabic
                else f"I detected journal entry numbers ({', '.join(detected)}), but no matching Odoo entries were found."
            ),
            "grid_data": None,
            "detected_entry_numbers": references,
            "detected_move_ids": move_ids,
        }

    all_line_ids: list[int] = []
    for move in moves:
        for line_id in move.get("line_ids") or []:
            try:
                all_line_ids.append(int(line_id))
            except Exception:
                continue

    move_lines = _read_move_lines(erp, sorted(set(all_line_ids)))
    grid_data = _build_grid_from_moves(conn, moves, move_lines, arabic)

    if arabic:
        msg = (
            f"✅ قرأت رقم/أرقام القيود من النص حتى مع وجود بيانات إضافية، وجلبت {len(moves)} قيد من Odoo. "
            f"تم عرض تفاصيل بنود القيود في الجدول."
        )
        sheet_name = "قيود Odoo المستخرجة"
    else:
        msg = (
            f"✅ I detected the journal entry number(s) inside the mixed text and fetched {len(moves)} Odoo entry/entries. "
            f"The journal item details are now shown in the sheet."
        )
        sheet_name = "Fetched Odoo Entries"

    return {
        "message": msg,
        "grid_data": grid_data,
        "active_sheet_name": sheet_name,
        "detected_entry_numbers": references,
        "detected_move_ids": move_ids,
        "odoo_move_count": len(moves),
    }
