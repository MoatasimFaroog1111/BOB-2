import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value

router = APIRouter()


class JournalEntryPostRequest(BaseModel):
    entry_number: Optional[str] = None
    move_id: Optional[int] = None
    company_id: Optional[int] = 1


def _many2one_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1] or "")
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


def _build_move_domain(payload: JournalEntryPostRequest) -> list[Any]:
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
                "account": _many2one_name(line.get("account_id")),
                "partner": _many2one_name(line.get("partner_id")),
                "label": line.get("name") or "",
                "debit": float(line.get("debit") or 0.0),
                "credit": float(line.get("credit") or 0.0),
            }
            for line in lines
        ],
    }


@router.post("/journal-entry/post")
def post_journal_entry(
    payload: JournalEntryPostRequest,
    db_session: Session = Depends(get_db),
):
    conn, erp = _read_saved_erp(db_session)
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

    move = moves[0]
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
            {"fields": ["id", "name", "ref", "date", "journal_id", "partner_id", "state", "payment_reference", "company_id"]},
        )
        if refreshed:
            move = refreshed[0]
    except Exception:
        move["state"] = "posted"

    lines = _read_move_lines(erp, move_id)
    return _move_payload(conn, move, lines, "Journal entry posted successfully in Odoo.")
