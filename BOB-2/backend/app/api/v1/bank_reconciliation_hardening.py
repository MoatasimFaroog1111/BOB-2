from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.erp.bank_reconciliation import (
    _run_matching,
    get_date_range,
    parse_file as parse_statement_file,
    transactions_from_odoo_move_lines,
)
from app.erp.bank_reconciliation_nlp import transaction_with_suggestion
from app.erp.factory import get_erp_provider
from app.models.bank_reconciliation import BankReconciliationAuditLog
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value
from app.security.file_validation import FileValidationError, sanitize_filename, validate_file_extension

router = APIRouter()


class SaveReconciliationReportRequest(BaseModel):
    audit_log_id: Optional[int] = None
    selected_bank_journal: dict[str, Any] | None = None
    statement_metadata: dict[str, Any] = Field(default_factory=dict)
    date_range_used: dict[str, Any] = Field(default_factory=dict)
    reconciliation_result: dict[str, Any] = Field(default_factory=dict)


class MarkSavedResponse(BaseModel):
    status: str
    report_id: int
    message: str


def _max_upload_bytes() -> int:
    return int(settings.MAX_UPLOAD_SIZE_MB) * 1024 * 1024


async def _read_validated_upload(file: UploadFile) -> tuple[bytes, str]:
    safe_name = sanitize_filename(file.filename or "bank_statement")
    try:
        validate_file_extension(safe_name)
    except FileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc.detail)) from exc

    payload = await file.read()
    await file.seek(0)

    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded bank statement is empty.")

    if len(payload) > _max_upload_bytes():
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )

    return payload, safe_name


def _write_temp_file(payload: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".csv"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(payload)
        return handle.name
    finally:
        handle.close()


def _get_active_erp_provider(db: Session):
    conn = db.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True,  # noqa: E712
    ).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ERP connection found. Please connect Odoo first.",
        )

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref or "{}"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to decrypt ERP connection credentials.") from exc

    return get_erp_provider(
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=secret_data.get("username", ""),
        password=secret_data.get("password", ""),
    )


def _select_bank_journal(erp: Any, company_id: int | None, bank_journal_id: int | None) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    journals = erp.discover_bank_journals(company_id=company_id)
    if not journals:
        raise HTTPException(status_code=400, detail="No active Odoo bank journals were found.")

    if bank_journal_id:
        selected = next((j for j in journals if int(j.get("journal_id") or 0) == int(bank_journal_id)), None)
        if not selected:
            raise HTTPException(status_code=400, detail="Selected bank journal was not found in Odoo.")
        return selected, journals, None

    if len(journals) == 1:
        return journals[0], journals, "Only one bank journal exists; it was selected automatically."

    raise HTTPException(status_code=400, detail="Please select a bank journal before reconciliation.")


def _audit_to_dict(log: BankReconciliationAuditLog, include_result: bool = False) -> dict[str, Any]:
    payload = {
        "id": log.id,
        "organization_id": log.organization_id,
        "company_id": log.company_id,
        "bank_journal_id": log.bank_journal_id,
        "bank_journal_name": log.bank_journal_name,
        "statement_filename": log.statement_filename,
        "statement_file_hash": log.statement_file_hash,
        "statement_file_size": log.statement_file_size,
        "date_from": log.date_from,
        "date_to": log.date_to,
        "statement_total": log.statement_total,
        "ledger_total": log.ledger_total,
        "difference": log.difference,
        "statement_count": log.statement_count,
        "ledger_count": log.ledger_count,
        "matched_count": log.matched_count,
        "smart_matched_count": log.smart_matched_count,
        "statement_only_count": log.statement_only_count,
        "ledger_only_count": log.ledger_only_count,
        "odoo_raw_count": log.odoo_raw_count,
        "status": log.status,
        "error_message": log.error_message,
        "created_by": log.created_by,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "updated_at": log.updated_at.isoformat() if log.updated_at else None,
    }
    if include_result:
        payload["result_json"] = log.result_json
    return payload


def _create_audit_log(
    db: Session,
    *,
    payload: dict[str, Any] | None,
    status_value: str,
    statement_metadata: dict[str, Any],
    selected_journal: dict[str, Any] | None,
    date_from: str | None,
    date_to: str | None,
    company_id: int | None,
    error_message: str | None = None,
) -> BankReconciliationAuditLog:
    result_payload = payload or {}
    log = BankReconciliationAuditLog(
        organization_id=1,
        company_id=company_id or (selected_journal or {}).get("company_id"),
        bank_journal_id=(selected_journal or {}).get("journal_id"),
        bank_journal_name=(selected_journal or {}).get("journal_name"),
        statement_filename=statement_metadata.get("filename"),
        statement_file_hash=statement_metadata.get("sha256"),
        statement_file_size=statement_metadata.get("size"),
        date_from=date_from,
        date_to=date_to,
        statement_total=result_payload.get("statement_total"),
        ledger_total=result_payload.get("ledger_total"),
        difference=result_payload.get("difference"),
        statement_count=result_payload.get("statement_count"),
        ledger_count=result_payload.get("ledger_count"),
        matched_count=len(result_payload.get("matched", []) or []),
        smart_matched_count=len(result_payload.get("smart_matched", []) or []),
        statement_only_count=len(result_payload.get("statement_only", []) or []),
        ledger_only_count=len(result_payload.get("ledger_only", []) or []),
        odoo_raw_count=result_payload.get("odoo_raw_count"),
        result_json=result_payload,
        status=status_value,
        error_message=error_message,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _build_result_payload(
    *,
    result: Any,
    odoo_raw_count: int,
    date_from: str | None,
    date_to: str | None,
    selected_journal: dict[str, Any],
    statement_metadata: dict[str, Any],
    warning: str | None,
) -> dict[str, Any]:
    statement_only_plain = [t.model_dump() for t in result.statement_only]
    ledger_only_plain = [t.model_dump() for t in result.ledger_only]
    statement_only = [transaction_with_suggestion(t, side="bank_only", peers=statement_only_plain) for t in result.statement_only]
    ledger_only = [transaction_with_suggestion(t, side="ledger_only", peers=ledger_only_plain) for t in result.ledger_only]

    return {
        "status": "success",
        "selected_bank_journal": selected_journal,
        "statement_metadata": statement_metadata,
        "statement_only": statement_only,
        "ledger_only": ledger_only,
        "matched": [match.model_dump() for match in result.matched],
        "smart_matched": [match.model_dump() for match in result.smart_matched],
        "statement_total": result.statement_total,
        "ledger_total": result.ledger_total,
        "difference": result.difference,
        "statement_count": result.statement_count,
        "ledger_count": result.ledger_count,
        "odoo_raw_count": odoo_raw_count,
        "date_range_used": {"from": date_from, "to": date_to},
        "warning": warning,
        "safe_to_post": False,
        "footer_note": "AI suggestions are for review only. No ERP posting was performed.",
    }


@router.get("/bank-journals")
def list_bank_journals(db: Session = Depends(get_db), company_id: Optional[int] = None):
    erp = _get_active_erp_provider(db)
    return {"status": "success", "items": erp.discover_bank_journals(company_id=company_id)}


@router.get("/bank-accounts")
def list_bank_accounts_alias(db: Session = Depends(get_db), company_id: Optional[int] = None):
    erp = _get_active_erp_provider(db)
    return {"status": "success", "items": erp.discover_bank_journals(company_id=company_id)}


@router.post("/bank-reconciliation")
async def bank_reconciliation(
    statement: UploadFile = File(...),
    db: Session = Depends(get_db),
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
    company_id: Optional[int] = Form(None),
    bank_journal_id: Optional[int] = Form(None),
):
    statement_path = ""
    statement_metadata: dict[str, Any] = {}
    selected_journal: dict[str, Any] | None = None
    try:
        payload, filename = await _read_validated_upload(statement)
        statement_metadata = {
            "filename": filename,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
        }
        statement_path = _write_temp_file(payload, filename)

        erp = _get_active_erp_provider(db)
        selected_journal, _journals, warning = _select_bank_journal(erp, company_id, bank_journal_id)

        statement_txns = parse_statement_file(statement_path)
        if not date_from or not date_to:
            auto_from, auto_to = get_date_range(statement_txns)
            date_from = date_from or auto_from
            date_to = date_to or auto_to

        odoo_move_lines = erp.fetch_bank_transactions(
            date_from=date_from,
            date_to=date_to,
            company_id=company_id,
            bank_journal_id=int(selected_journal["journal_id"]),
            bank_account_id=selected_journal.get("account_id"),
        )
        ledger_txns = transactions_from_odoo_move_lines(odoo_move_lines)
        result = _run_matching(statement_txns, ledger_txns)
        response_payload = _build_result_payload(
            result=result,
            odoo_raw_count=len(odoo_move_lines),
            date_from=date_from,
            date_to=date_to,
            selected_journal=selected_journal,
            statement_metadata=statement_metadata,
            warning=warning,
        )
        audit_log = _create_audit_log(
            db,
            payload=response_payload,
            status_value="generated",
            statement_metadata=statement_metadata,
            selected_journal=selected_journal,
            date_from=date_from,
            date_to=date_to,
            company_id=company_id,
        )
        response_payload["audit_log_id"] = audit_log.id
        response_payload["report_status"] = audit_log.status
        return response_payload
    except HTTPException:
        raise
    except Exception as exc:
        try:
            if statement_metadata:
                _create_audit_log(
                    db,
                    payload=None,
                    status_value="failed",
                    statement_metadata=statement_metadata,
                    selected_journal=selected_journal,
                    date_from=date_from,
                    date_to=date_to,
                    company_id=company_id,
                    error_message=str(exc),
                )
        except Exception:
            db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Bank reconciliation failed: {exc}") from exc
    finally:
        if statement_path and os.path.exists(statement_path):
            os.remove(statement_path)


@router.post("/bank-statement-parse")
async def parse_bank_statement_only(
    statement: UploadFile = File(...),
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
):
    statement_path = ""
    try:
        payload, filename = await _read_validated_upload(statement)
        statement_path = _write_temp_file(payload, filename)
        statement_txns = parse_statement_file(statement_path)
        total = round(sum(t.amount for t in statement_txns), 2)
        return {
            "status": "success",
            "statement_only": [transaction_with_suggestion(t, side="bank_only") for t in statement_txns],
            "ledger_only": [],
            "matched": [],
            "smart_matched": [],
            "statement_total": total,
            "ledger_total": 0.0,
            "difference": total,
            "statement_count": len(statement_txns),
            "ledger_count": 0,
            "odoo_raw_count": 0,
            "date_range_used": {"from": date_from, "to": date_to},
            "safe_to_post": False,
        }
    finally:
        if statement_path and os.path.exists(statement_path):
            os.remove(statement_path)


@router.get("/bank-reconciliation/reports")
def list_reconciliation_reports(db: Session = Depends(get_db), limit: int = 50):
    rows = (
        db.query(BankReconciliationAuditLog)
        .order_by(BankReconciliationAuditLog.created_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    return {"status": "success", "items": [_audit_to_dict(row) for row in rows]}


@router.get("/bank-reconciliation/reports/{report_id}")
def get_reconciliation_report(report_id: int, db: Session = Depends(get_db)):
    log = db.query(BankReconciliationAuditLog).filter(BankReconciliationAuditLog.id == report_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Reconciliation report not found.")
    return {"status": "success", "item": _audit_to_dict(log, include_result=True)}


@router.post("/bank-reconciliation/reports")
def save_reconciliation_report(payload: SaveReconciliationReportRequest, db: Session = Depends(get_db)):
    if payload.audit_log_id:
        log = db.query(BankReconciliationAuditLog).filter(BankReconciliationAuditLog.id == payload.audit_log_id).first()
        if not log:
            raise HTTPException(status_code=404, detail="Reconciliation audit log not found.")
        if log.status != "saved":
            log.status = "saved"
            db.commit()
            db.refresh(log)
        return {"status": "success", "report_id": log.id, "message": "Reconciliation report saved successfully."}

    selected = payload.selected_bank_journal or {}
    result_payload = payload.reconciliation_result or {}
    statement_metadata = payload.statement_metadata or {}
    date_range = payload.date_range_used or {}
    log = _create_audit_log(
        db,
        payload=result_payload,
        status_value="saved",
        statement_metadata=statement_metadata,
        selected_journal=selected,
        date_from=date_range.get("from"),
        date_to=date_range.get("to"),
        company_id=selected.get("company_id"),
    )
    return {"status": "success", "report_id": log.id, "message": "Reconciliation report saved successfully."}


@router.post("/bank-reconciliation/reports/{report_id}/save")
def mark_reconciliation_report_saved(report_id: int, db: Session = Depends(get_db)):
    log = db.query(BankReconciliationAuditLog).filter(BankReconciliationAuditLog.id == report_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Reconciliation report not found.")
    log.status = "saved"
    db.commit()
    db.refresh(log)
    return {"status": "success", "report_id": log.id, "message": "Reconciliation report saved successfully."}
