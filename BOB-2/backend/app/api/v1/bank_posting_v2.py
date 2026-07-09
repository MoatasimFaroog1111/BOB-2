import json
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value

router = APIRouter()


class BankPostingLineV2(BaseModel):
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


class BankPostingRequestV2(BaseModel):
    company_id: Optional[int] = None
    journal_type: str = "bank"
    journal_id: Optional[int] = None
    date: str = ""
    ref: str = ""
    filename: str = "bank_statement_reconciliation"
    amount: float = 0.0
    partner_name: str = ""
    attachment_name: str = ""
    attachment_mimetype: str = ""
    attachment_content_base64: str = ""
    lines: List[BankPostingLineV2]


def safe_date(value: str) -> str:
    try:
        if value:
            datetime.strptime(value, "%Y-%m-%d")
            return value
    except Exception:
        pass
    return str(date.today())


def normalized_journal_type(value: str) -> str:
    raw = (value or "bank").strip().lower()
    aliases = {
        "bank": "bank",
        "cash": "bank",
        "misc": "general",
        "miscellaneous": "general",
        "miscellaneous_operations": "general",
        "general": "general",
        "entry": "general",
        "vendor_bill": "purchase",
        "vendor bills": "purchase",
        "bill": "purchase",
        "purchase": "purchase",
        "customer_invoice": "sale",
        "customer invoices": "sale",
        "invoice": "sale",
        "sale": "sale",
        "sales": "sale",
    }
    return aliases.get(raw, "bank")


def add_analytic(vals: dict, analytic_account_id: Optional[int]) -> dict:
    if analytic_account_id:
        vals["analytic_account_id"] = int(analytic_account_id)
        vals["analytic_distribution"] = {str(int(analytic_account_id)): 100.0}
    return vals


def remove_analytic(move_vals: dict) -> dict:
    clean = dict(move_vals)
    clean_lines = []
    for cmd in clean.get("line_ids", []):
        if isinstance(cmd, tuple) and len(cmd) == 3 and isinstance(cmd[2], dict):
            vals = dict(cmd[2])
            vals.pop("analytic_account_id", None)
            vals.pop("analytic_distribution", None)
            clean_lines.append((cmd[0], cmd[1], vals))
        else:
            clean_lines.append(cmd)
    clean["line_ids"] = clean_lines
    return clean


def normalize_attachment_content(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "," in raw and raw.lower().startswith("data:"):
        return raw.split(",", 1)[1]
    return raw


def attach_document_to_move(erp, move_id: int, payload: BankPostingRequestV2) -> tuple[Optional[int], str]:
    content = normalize_attachment_content(payload.attachment_content_base64)
    if not content:
        return None, ""
    name = payload.attachment_name or f"{payload.ref or 'bank-reconciliation-entry'}.pdf"
    vals = {
        "name": name,
        "res_model": "account.move",
        "res_id": int(move_id),
        "type": "binary",
        "datas": content,
    }
    if payload.attachment_mimetype:
        vals["mimetype"] = payload.attachment_mimetype
    attachment_id = erp.execute_kw("ir.attachment", "create", [vals])
    return int(attachment_id), name


@router.post("/register-bank-reconciliation-entry-v2")
def register_bank_reconciliation_entry_v2(payload: BankPostingRequestV2, db_session: Session = Depends(get_db)):
    if not payload.lines or len(payload.lines) < 2:
        raise HTTPException(status_code=400, detail="At least two journal lines are required.")

    total_debit = round(sum(float(line.debit or 0.0) for line in payload.lines), 2)
    total_credit = round(sum(float(line.credit or 0.0) for line in payload.lines), 2)
    if total_debit != total_credit:
        raise HTTPException(status_code=400, detail=f"Journal entry is not balanced: debit={total_debit}, credit={total_credit}")

    conn = db_session.query(ERPConnection).filter(ERPConnection.organization_id == 1, ERPConnection.is_active == True).first()
    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret.get("username")
        password = secret.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(provider=conn.provider, url=conn.base_url, db=conn.database_name or "", username=username, password=password)

        company_id = payload.company_id
        if not company_id:
            users = erp.execute_kw("res.users", "search_read", [[["login", "=", username]]], {"fields": ["company_id"], "limit": 1})
            company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        journal_type = normalized_journal_type(payload.journal_type)
        journal_id = payload.journal_id or False
        journal_name = ""

        if journal_id:
            domain = [["id", "=", int(journal_id)]]
            if company_id:
                domain.append(["company_id", "=", int(company_id)])
            journals = erp.execute_kw("account.journal", "search_read", [domain], {"fields": ["id", "name", "type"], "limit": 1})
            if not journals:
                raise ValueError("Selected journal does not belong to the selected company.")
            journal_name = journals[0].get("name") or ""
            journal_type = journals[0].get("type") or journal_type
        else:
            for candidate in [journal_type, "general"]:
                domain = [["type", "=", candidate]]
                if company_id:
                    domain.append(["company_id", "=", int(company_id)])
                journals = erp.execute_kw("account.journal", "search_read", [domain], {"fields": ["id", "name", "type"], "limit": 1})
                if journals:
                    journal_id = journals[0]["id"]
                    journal_name = journals[0].get("name") or ""
                    journal_type = journals[0].get("type") or candidate
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
            line_ids.append((0, 0, add_analytic(vals, line.analytic_account_id)))

        move_vals = {
            "move_type": "entry",
            "date": safe_date(payload.date),
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
            move_id = erp.execute_kw("account.move", "create", [remove_analytic(move_vals)])

        move_name = f"JE/{move_id}"
        try:
            created = erp.execute_kw("account.move", "read", [[move_id]], {"fields": ["name"]})
            if created and created[0].get("name"):
                move_name = created[0]["name"]
        except Exception:
            pass

        attachment_id = None
        attachment_name = ""
        attachment_error = ""
        try:
            attachment_id, attachment_name = attach_document_to_move(erp, int(move_id), payload)
        except Exception as attachment_exc:
            attachment_error = str(attachment_exc)

        base_url = conn.base_url.rstrip("/")
        return {
            "status": "success",
            "message": "Bank reconciliation entry created successfully in Odoo",
            "move_id": move_id,
            "move_name": move_name,
            "odoo_url": f"{base_url}/web#id={move_id}&model=account.move&view_type=form",
            "attachment_id": attachment_id,
            "attachment_name": attachment_name,
            "attachment_error": attachment_error,
            "company_id": company_id,
            "journal_id": journal_id,
            "journal_name": journal_name,
            "journal_type": journal_type,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create bank reconciliation entry in Odoo: {str(e)}")
