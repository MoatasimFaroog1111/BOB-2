import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value

router = APIRouter()

ACCOUNT_CODE_PATTERN = re.compile(r"(?:^|[^\d.])([0-9][0-9]{4,9})(?![\d.])")
ENTRY_REFERENCE_PATTERN = re.compile(
    r"\b[A-Z][A-Z0-9]{1,12}\s*/\s*\d{4}\s*(?:/\s*\d{1,2})?\s*/\s*\d{3,8}\b",
    re.IGNORECASE,
)


class JournalEntryPostRequest(BaseModel):
    entry_number: Optional[str] = None
    move_id: Optional[int] = None
    company_id: Optional[int] = 1


class JournalEntryUpdateLine(BaseModel):
    entry_number: Optional[str] = None
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    partner_name: Optional[str] = None
    label: Optional[str] = None
    debit: Optional[float] = 0.0
    credit: Optional[float] = 0.0


class JournalEntryUpdateRequest(BaseModel):
    entry_number: Optional[str] = None
    move_id: Optional[int] = None
    company_id: Optional[int] = 1
    date: Optional[str] = None
    ref: Optional[str] = None
    rows: list[JournalEntryUpdateLine]


def _many2one_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1] or "")
    return ""


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except Exception:
            return None
    if isinstance(value, int):
        return value
    return None


def _extract_account_code(*values: Optional[str]) -> str:
    for value in values:
        text = str(value or "").replace("↗", "").strip()
        if not text:
            continue
        # Do not accidentally pick numbers from Odoo move references such as MISC/2024/12/0040.
        if ENTRY_REFERENCE_PATTERN.search(text):
            continue
        for match in ACCOUNT_CODE_PATTERN.finditer(text):
            code = (match.group(1) or "").strip()
            if code:
                return code
    return ""


def _read_saved_erp(db_session: Session):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True,  # noqa: E712 - keep existing project style
    ).first()

    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ERP connection found.",
        )

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt ERP connection credentials.",
        ) from exc

    erp = get_erp_provider(
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=username,
        password=password,
    )
    return conn, erp


def _build_move_domain(payload: JournalEntryPostRequest | JournalEntryUpdateRequest) -> list[Any]:
    domain: list[Any] = []

    if payload.move_id:
        domain.append(["id", "=", payload.move_id])
    elif payload.entry_number:
        entry_number = payload.entry_number.strip()
        if not entry_number:
            raise HTTPException(status_code=400, detail="Entry number is empty.")
        domain.extend([
            "|",
            "|",
            ["name", "=", entry_number],
            ["ref", "=", entry_number],
            ["payment_reference", "=", entry_number],
        ])
    else:
        raise HTTPException(status_code=400, detail="entry_number or move_id is required.")

    if payload.company_id:
        domain.append(["company_id", "=", payload.company_id])

    return domain


def _read_matching_move(erp, payload: JournalEntryPostRequest | JournalEntryUpdateRequest) -> dict[str, Any]:
    domain = _build_move_domain(payload)
    try:
        moves = erp.execute_kw(
            "account.move",
            "search_read",
            [domain],
            {
                "fields": [
                    "id",
                    "name",
                    "ref",
                    "date",
                    "journal_id",
                    "partner_id",
                    "state",
                    "payment_reference",
                    "company_id",
                    "line_ids",
                ],
                "limit": 2,
            },
        ) or []
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read Odoo journal entry: {exc}") from exc

    if not moves:
        raise HTTPException(status_code=404, detail="Matching Odoo journal entry was not found.")
    if len(moves) > 1:
        raise HTTPException(status_code=409, detail="More than one Odoo journal entry matched this reference.")
    return moves[0]


def _read_move_lines(erp, move_id: int) -> list[dict[str, Any]]:
    try:
        return erp.execute_kw(
            "account.move.line",
            "search_read",
            [[["move_id", "=", move_id]]],
            {
                "fields": ["id", "account_id", "name", "debit", "credit", "partner_id"],
                "order": "id asc",
                "limit": 500,
            },
        ) or []
    except Exception:
        return []


def _account_payload(account_value: Any) -> tuple[str, str]:
    account_name = _many2one_name(account_value)
    account_code = _extract_account_code(account_name)
    return account_code, account_name


def _move_payload(conn, move: dict[str, Any], lines: list[dict[str, Any]], message: str) -> dict[str, Any]:
    move_id = move.get("id")
    base_url = (conn.base_url or "").rstrip("/")
    odoo_url = f"{base_url}/web#id={move_id}&model=account.move&view_type=form" if move_id and base_url else ""
    return {
        "status": "success",
        "message": message,
        "move_id": move_id,
        "entry_number": move.get("name") or "",
        "state": move.get("state") or "",
        "date": move.get("date") or "",
        "journal": _many2one_name(move.get("journal_id")),
        "partner": _many2one_name(move.get("partner_id")),
        "ref": move.get("ref") or move.get("payment_reference") or "",
        "odoo_url": odoo_url,
        "lines": [
            {
                "account_code": _account_payload(line.get("account_id"))[0],
                "account": _account_payload(line.get("account_id"))[1],
                "partner": _many2one_name(line.get("partner_id")),
                "label": line.get("name") or "",
                "debit": float(line.get("debit") or 0.0),
                "credit": float(line.get("credit") or 0.0),
            }
            for line in lines
        ],
    }


def _find_account_id(erp, account_code: str, account_name: str | None, company_id: int | None) -> int:
    code = _extract_account_code(account_code, account_name)
    if not code:
        raise HTTPException(
            status_code=400,
            detail="Each line must contain a clear account code from the sheet, for example 999002 or Historical Adjustment 999002.",
        )

    domains: list[list[Any]] = [["code", "=", code]]
    if company_id:
        domains.insert(0, ["company_ids", "in", [company_id]])

    try:
        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [domains],
            {"fields": ["id", "code", "name"], "limit": 2},
        ) or []
    except Exception:
        accounts = []

    if not accounts:
        try:
            accounts = erp.execute_kw(
                "account.account",
                "search_read",
                [[["code", "=", code]]],
                {"fields": ["id", "code", "name"], "limit": 2},
            ) or []
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to search account {code}: {exc}") from exc

    if not accounts:
        raise HTTPException(status_code=404, detail=f"Account code {code} was not found in Odoo.")
    if len(accounts) > 1:
        raise HTTPException(status_code=409, detail=f"More than one Odoo account matched code {code}.")
    return int(accounts[0]["id"])


def _find_partner_id(erp, partner_name: str | None, company_id: int | None) -> int | None:
    name = str(partner_name or "").strip()
    if not name:
        return None

    domains: list[list[Any]] = [["name", "=", name]]
    if company_id:
        domains.append(["company_id", "in", [False, company_id]])

    try:
        partners = erp.execute_kw(
            "res.partner",
            "search_read",
            [domains],
            {"fields": ["id", "name"], "limit": 2},
        ) or []
    except Exception:
        partners = []

    if not partners:
        try:
            partners = erp.execute_kw(
                "res.partner",
                "search_read",
                [[["name", "ilike", name]]],
                {"fields": ["id", "name"], "limit": 2},
            ) or []
        except Exception:
            return None

    if len(partners) == 1:
        return int(partners[0]["id"])
    return None


def _safe_amount(value: float | int | str | None) -> float:
    try:
        return round(float(str(value or 0).replace(",", "")), 2)
    except Exception:
        return 0.0


def _build_line_update_vals(erp, row: JournalEntryUpdateLine, company_id: int | None) -> dict[str, Any]:
    debit = _safe_amount(row.debit)
    credit = _safe_amount(row.credit)
    if debit and credit:
        raise HTTPException(status_code=400, detail="A journal item cannot have both debit and credit values.")

    vals: dict[str, Any] = {
        "account_id": _find_account_id(erp, row.account_code or "", row.account_name, company_id),
        "name": str(row.label or "/"),
        "debit": debit,
        "credit": credit,
    }
    partner_id = _find_partner_id(erp, row.partner_name, company_id)
    if partner_id:
        vals["partner_id"] = partner_id
    return vals


@router.post("/journal-entry/post")
def post_journal_entry(
    payload: JournalEntryPostRequest,
    db_session: Session = Depends(get_db),
):
    conn, erp = _read_saved_erp(db_session)
    move = _read_matching_move(erp, payload)

    move_id = int(move["id"])
    current_state = move.get("state") or ""

    if current_state == "posted":
        lines = _read_move_lines(erp, move_id)
        return _move_payload(conn, move, lines, "Journal entry is already posted in Odoo.")

    if current_state != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Only draft entries can be posted. Current Odoo state is: {current_state}",
        )

    try:
        erp.execute_kw("account.move", "action_post", [[move_id]])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to post Odoo journal entry: {exc}") from exc

    try:
        refreshed = erp.execute_kw(
            "account.move",
            "read",
            [[move_id]],
            {"fields": ["id", "name", "ref", "date", "journal_id", "partner_id", "state", "payment_reference", "company_id", "line_ids"]},
        )
        if refreshed:
            move = refreshed[0]
    except Exception:
        move["state"] = "posted"

    lines = _read_move_lines(erp, move_id)
    return _move_payload(conn, move, lines, "Journal entry posted successfully in Odoo.")


@router.post("/journal-entry/update")
def update_journal_entry_from_sheet(
    payload: JournalEntryUpdateRequest,
    db_session: Session = Depends(get_db),
):
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No sheet rows were provided for updating the journal entry.")

    conn, erp = _read_saved_erp(db_session)
    move = _read_matching_move(erp, payload)
    move_id = int(move["id"])
    current_state = move.get("state") or ""

    if current_state != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only draft Odoo journal entries can be updated from the sheet. "
                f"Current state is: {current_state}. Create a reversal/correction entry for posted moves."
            ),
        )

    current_lines = _read_move_lines(erp, move_id)
    if len(current_lines) != len(payload.rows):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Sheet lines count ({len(payload.rows)}) does not match Odoo journal items count ({len(current_lines)}). "
                "Refusing to guess line mapping. Fetch the entry again, edit it, then retry."
            ),
        )

    move_vals: dict[str, Any] = {}
    if payload.date:
        move_vals["date"] = payload.date
    if payload.ref is not None:
        move_vals["ref"] = payload.ref

    try:
        if move_vals:
            erp.execute_kw("account.move", "write", [[move_id], move_vals])

        for line, row in zip(current_lines, payload.rows):
            vals = _build_line_update_vals(erp, row, payload.company_id)
            erp.execute_kw("account.move.line", "write", [[int(line["id"])], vals])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to update Odoo journal entry from sheet: {exc}") from exc

    refreshed = erp.execute_kw(
        "account.move",
        "read",
        [[move_id]],
        {"fields": ["id", "name", "ref", "date", "journal_id", "partner_id", "state", "payment_reference", "company_id", "line_ids"]},
    )
    if refreshed:
        move = refreshed[0]

    lines = _read_move_lines(erp, move_id)
    return _move_payload(
        conn,
        move,
        lines,
        f"Journal entry {move.get('name') or payload.entry_number or move_id} was updated from the sheet draft successfully.",
    )
