import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.erp.providers.odoo import OdooProvider
from app.models.core import AuditLog, ERPConnection
from app.security.encryption import decrypt_value
from app.services.bank_reconciliation_matching import (
    odoo_lines_from_move_lines,
    parse_bank_statement_file,
    parse_bank_statement_text,
    reconcile_bank_to_odoo,
)

router = APIRouter()


def _get_odoo_provider(db: Session):
    conn = db.query(ERPConnection).filter(ERPConnection.organization_id == 1, ERPConnection.is_active == True).first()
    if conn:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref)) if conn.encrypted_secret_ref else {}
        return get_erp_provider(provider=conn.provider, url=conn.base_url, db=conn.database_name or "", username=secret_data.get("username", ""), password=secret_data.get("password", ""))
    if all([settings.ODOO_URL, settings.ODOO_DB, settings.ODOO_USERNAME, settings.ODOO_PASSWORD]):
        return OdooProvider(settings.ODOO_URL, settings.ODOO_DB, settings.ODOO_USERNAME, settings.ODOO_PASSWORD)
    raise ValueError("Odoo connection failure: no active BOB ERP connection and ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_PASSWORD are not fully configured.")


@router.post("/match")
def match_bank_reconciliation(
    statement: Optional[UploadFile] = File(None),
    pasted_text: Optional[str] = Form(None),
    date_from: str = Form(...),
    date_to: str = Form(...),
    odoo_bank_journal_id: Optional[int] = Form(None),
    odoo_bank_account_id: Optional[int] = Form(None),
    date_tolerance_days: int = Form(3),
    db: Session = Depends(get_db),
):
    """Read bank statement text/file, fetch posted Odoo bank ledger lines, and return a report only."""
    if not date_from or not date_to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from and date_to are required.")
    if not statement and not pasted_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a bank statement file or provide pasted_text.")

    temp_path = ""
    try:
        if statement:
            suffix = Path(statement.filename or "statement.csv").suffix or ".csv"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                shutil.copyfileobj(statement.file, tmp)
                temp_path = tmp.name
            bank_lines = parse_bank_statement_file(temp_path)
        else:
            bank_lines = parse_bank_statement_text(pasted_text or "")

        erp = _get_odoo_provider(db)
        if not hasattr(erp, "fetch_bank_ledger_lines"):
            raise ValueError("Odoo provider does not support bank ledger fetching.")
        raw_lines = erp.fetch_bank_ledger_lines(date_from=date_from, date_to=date_to, journal_id=odoo_bank_journal_id, account_id=odoo_bank_account_id)
        if not raw_lines:
            raise ValueError("No ledger lines found for the selected posted Odoo bank journal/account and date range.")
        report = reconcile_bank_to_odoo(bank_lines, odoo_lines_from_move_lines(raw_lines), tolerance_days=date_tolerance_days)
        payload = report.model_dump()
        payload["status"] = "success"
        payload["date_range"] = {"from": date_from, "to": date_to}
        payload["selected_odoo"] = {"journal_id": odoo_bank_journal_id, "account_id": odoo_bank_account_id}
        payload["audit_safe"] = {"modified_odoo": False, "posted_entries": False, "requires_separate_approval_for_future_actions": True}
        db.add(AuditLog(organization_id=1, action="bank_reconciliation_match_report", entity_type="bank_reconciliation", entity_id=None, details={"summary": payload["summary"], "date_range": payload["date_range"], "selected_odoo": payload["selected_odoo"]}))
        db.commit()
        return payload
    except HTTPException:
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Bank reconciliation matching failed: {exc}") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
