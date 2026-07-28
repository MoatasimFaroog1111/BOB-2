"""Blocking accounting operations executed exclusively by background workers."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.db.database import SessionLocal
from app.erp.bank_reconciliation import (
    _run_matching,
    get_date_range,
    parse_file as parse_statement_file,
    transactions_from_odoo_move_lines,
)
from app.erp.document_ai import GuardianDocumentAI
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value


def analyze_documents(files: list[dict[str, str]]) -> dict[str, Any]:
    ai = GuardianDocumentAI()
    results: list[dict[str, Any]] = []
    for item in files:
        filename = item["filename"]
        try:
            analysis = ai.analyze_document(item["path"])
            analysis["original_filename"] = filename
            results.append(
                {
                    "filename": filename,
                    "status": "analyzed",
                    "result": analysis,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "filename": filename,
                    "status": "error",
                    "message": str(exc)[:500],
                }
            )
    return {
        "status": "batch_analyzed",
        "file_count": len(files),
        "success_count": sum(item["status"] == "analyzed" for item in results),
        "error_count": sum(item["status"] == "error" for item in results),
        "results": results,
    }


def match_documents(files: list[dict[str, str]]) -> dict[str, Any]:
    """Execute the removed legacy matcher inside the worker process only."""

    from app.api.v1.erp import match_documents as legacy_match_documents

    db = SessionLocal()
    try:
        with ExitStack() as stack:
            uploads: list[UploadFile] = []
            for item in files:
                handle = stack.enter_context(open(item["path"], "rb"))
                uploads.append(UploadFile(file=handle, filename=item["filename"]))
            result = legacy_match_documents(uploads, db)
        return result
    finally:
        db.close()


def parse_bank_statement(
    file_item: dict[str, str],
    *,
    date_from: str | None,
    date_to: str | None,
) -> dict[str, Any]:
    statement_txns = parse_statement_file(file_item["path"])
    statement_total = round(sum(transaction.amount for transaction in statement_txns), 2)
    return {
        "status": "success",
        "statement_only": [transaction.model_dump() for transaction in statement_txns],
        "ledger_only": [],
        "matched": [],
        "smart_matched": [],
        "statement_total": statement_total,
        "ledger_total": 0.0,
        "difference": statement_total,
        "statement_count": len(statement_txns),
        "ledger_count": 0,
        "odoo_raw_count": 0,
        "date_range_used": {"from": date_from, "to": date_to},
    }


def _tenant_erp_connection(organization_id: int):
    db = SessionLocal()
    try:
        connection = (
            db.query(ERPConnection)
            .filter(
                ERPConnection.organization_id == organization_id,
                ERPConnection.is_active.is_(True),
            )
            .order_by(ERPConnection.id.asc())
            .first()
        )
        if connection is None or not connection.encrypted_secret_ref:
            raise RuntimeError("erp_connection_missing")
        credentials = json.loads(decrypt_value(connection.encrypted_secret_ref))
        return get_erp_provider(
            provider=connection.provider,
            url=connection.base_url,
            db=connection.database_name or "",
            username=str(credentials.get("username") or ""),
            password=str(credentials.get("password") or ""),
        )
    finally:
        db.close()


def reconcile_bank_statement(
    organization_id: int,
    file_item: dict[str, str],
    *,
    date_from: str | None,
    date_to: str | None,
    company_id: int | None,
) -> dict[str, Any]:
    statement_txns = parse_statement_file(file_item["path"])
    if not date_from or not date_to:
        auto_from, auto_to = get_date_range(statement_txns)
        date_from = date_from or auto_from
        date_to = date_to or auto_to

    erp = _tenant_erp_connection(organization_id)
    odoo_move_lines = erp.fetch_bank_transactions(
        date_from=date_from,
        date_to=date_to,
        company_id=company_id,
    )
    ledger_txns = transactions_from_odoo_move_lines(odoo_move_lines)
    result = _run_matching(statement_txns, ledger_txns)
    return {
        "status": "success",
        "statement_only": [item.model_dump() for item in result.statement_only],
        "ledger_only": [item.model_dump() for item in result.ledger_only],
        "matched": [item.model_dump() for item in result.matched],
        "smart_matched": [item.model_dump() for item in result.smart_matched],
        "statement_total": result.statement_total,
        "ledger_total": result.ledger_total,
        "difference": result.difference,
        "statement_count": result.statement_count,
        "ledger_count": result.ledger_count,
        "odoo_raw_count": len(odoo_move_lines),
        "date_range_used": {"from": date_from, "to": date_to},
    }


def chat_spreadsheet(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute the removed legacy LLM handler inside the worker process only."""

    from app.api.v1.erp import (
        ChatSpreadsheetRequest,
        chat_spreadsheet as legacy_chat_spreadsheet,
    )

    db = SessionLocal()
    try:
        request = ChatSpreadsheetRequest.model_validate(payload)
        result = legacy_chat_spreadsheet(request, db)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if not isinstance(result, dict):
            raise RuntimeError("spreadsheet_llm_result_invalid")
        return result
    finally:
        db.close()
