import base64
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.core import ERPConnection
from app.erp.factory import get_erp_provider
from app.security.encryption import decrypt_value

logger = logging.getLogger(__name__)

router = APIRouter()


class BankPostingLine(BaseModel):
    account_id: int
    account_name: str = ""
    account_code: str = ""
    debit: float = 0.0
    credit: float = 0.0
    name: str
    partner_id: Optional[int] = None
    partner_name: str = ""
    analytic_account_id: Optional[int] = None
    analytic_account_name: str = ""


class BankPostingRequest(BaseModel):
    company_id: Optional[int] = None
    date: str = ""
    ref: str = ""
    filename: str = "bank_statement_reconciliation"
    amount: float = 0.0
    partner_name: str = ""
    file_path: Optional[str] = None
    lines: List[BankPostingLine]


def _safe_date(value: str) -> str:
    if value:
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except Exception:
            pass
    return str(date.today())


def _inject_analytic(vals: dict, analytic_account_id: Optional[int]) -> dict:
    if analytic_account_id:
        vals["analytic_account_id"] = int(analytic_account_id)
        vals["analytic_distribution"] = {str(int(analytic_account_id)): 100.0}
    return vals


def _strip_analytic(move_vals: dict) -> dict:
    clean_vals = dict(move_vals)
    clean_lines = []
    for cmd in clean_vals.get("line_ids", []):
        if isinstance(cmd, tuple) and len(cmd) == 3 and isinstance(cmd[2], dict):
            vals = dict(cmd[2])
            vals.pop("analytic_account_id", None)
            vals.pop("analytic_distribution", None)
            clean_lines.append((cmd[0], cmd[1], vals))
        else:
            clean_lines.append(cmd)
    clean_vals["line_ids"] = clean_lines
    return clean_vals


def _upload_attachment_to_odoo(move_id: int, filename: str, file_path: str, db_session: Session) -> int:
    """Read a local file, base64-encode it, and attach it to an account.move in Odoo as an ir.attachment.

    Args:
        move_id:    The Odoo account.move record ID to attach the file to.
        filename:   The display name for the attachment in Odoo.
        file_path:  Absolute or relative path to the local file on disk.
        db_session: An active SQLAlchemy session used to look up the ERP connection.

    Returns:
        The newly created ir.attachment record ID.

    Raises:
        FileNotFoundError: If the file at *file_path* does not exist.
        RuntimeError:      If no active ERP connection is configured.
        Exception:         Propagates any Odoo XML-RPC error.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Attachment file not found: {file_path}")

    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True,
    ).first()
    if not conn:
        raise RuntimeError("No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception as exc:
        raise RuntimeError(f"Failed to decrypt ERP connection credentials: {exc}") from exc

    erp = get_erp_provider(
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=username,
        password=password,
    )

    with open(path, "rb") as fh:
        file_data = base64.b64encode(fh.read()).decode("utf-8")

    attachment_id = erp.execute_kw(
        "ir.attachment",
        "create",
        [{
            "name": filename,
            "type": "binary",
            "datas": file_data,
            "res_model": "account.move",
            "res_id": move_id,
        }],
    )
    logger.info("Attachment created in Odoo: attachment_id=%s linked to account.move id=%s", attachment_id, move_id)
    return attachment_id


@router.post("/register-bank-reconciliation-entry")
def register_bank_reconciliation_entry(payload: BankPostingRequest, db_session: Session = Depends(get_db)):
    if not payload.lines or len(payload.lines) < 2:
        raise HTTPException(status_code=400, detail="At least two balanced journal lines are required.")

    total_debit = round(sum(float(line.debit or 0.0) for line in payload.lines), 2)
    total_credit = round(sum(float(line.credit or 0.0) for line in payload.lines), 2)
    if total_debit != total_credit:
        raise HTTPException(status_code=400, detail=f"Journal entry is not balanced: debit={total_debit}, credit={total_credit}")

    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True,
    ).first()
    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        company_id = payload.company_id
        if not company_id:
            users = erp.execute_kw(
                "res.users",
                "search_read",
                [[["login", "=", username]]],
                {"fields": ["company_id"], "limit": 1},
            )
            company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        journal_id = False
        for journal_type in ["bank", "general"]:
            domain = [["type", "=", journal_type]]
            if company_id:
                domain.append(["company_id", "=", company_id])
            journals = erp.execute_kw(
                "account.journal",
                "search_read",
                [domain],
                {"fields": ["id", "name"], "limit": 1},
            )
            if journals:
                journal_id = journals[0]["id"]
                break

        line_ids = []
        for line in payload.lines:
            vals = {
                "account_id": int(line.account_id),
                "name": line.name or payload.ref or "Bank reconciliation entry",
                "debit": float(line.debit or 0.0),
                "credit": float(line.credit or 0.0),
            }
            if line.partner_id:
                vals["partner_id"] = int(line.partner_id)
            vals = _inject_analytic(vals, line.analytic_account_id)
            line_ids.append((0, 0, vals))

        move_vals = {
            "move_type": "entry",
            "date": _safe_date(payload.date),
            "ref": payload.ref or f"Bank statement reconciliation {payload.filename}",
            "line_ids": line_ids,
        }
        if company_id:
            move_vals["company_id"] = int(company_id)
        if journal_id:
            move_vals["journal_id"] = int(journal_id)

        try:
            move_id = erp.execute_kw("account.move", "create", [move_vals])
        except Exception as create_err:
            if "analytic" not in str(create_err).lower():
                raise
            move_id = erp.execute_kw("account.move", "create", [_strip_analytic(move_vals)])

        move_name = f"JE/{move_id}"
        try:
            created = erp.execute_kw("account.move", "read", [[move_id]], {"fields": ["name"]})
            if created and created[0].get("name"):
                move_name = created[0]["name"]
        except Exception:
            pass

        # Attach the uploaded document to the journal entry when a file path is provided.
        attachment_id = None
        if payload.file_path:
            try:
                attachment_id = _upload_attachment_to_odoo(
                    move_id=move_id,
                    filename=payload.filename,
                    file_path=payload.file_path,
                    db_session=db_session,
                )
            except Exception as att_err:
                # Attachment failure must not roll back a successfully created journal entry.
                logger.warning(
                    "Failed to attach file '%s' to account.move id=%s: %s",
                    payload.file_path,
                    move_id,
                    att_err,
                )

        base_url = conn.base_url.rstrip("/")
        return {
            "status": "success",
            "message": "Bank reconciliation entry created successfully in Odoo",
            "move_id": move_id,
            "move_name": move_name,
            "odoo_url": f"{base_url}/web#id={move_id}&model=account.move&view_type=form",
            "company_id": company_id,
            "attachment_id": attachment_id,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create bank reconciliation entry in Odoo: {str(e)}")
