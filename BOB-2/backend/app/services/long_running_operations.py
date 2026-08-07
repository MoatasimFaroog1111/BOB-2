"""Blocking accounting operations executed exclusively by background workers."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from typing import Any

from fastapi import UploadFile

from app.db.database import SessionLocal
from app.erp.document_ai import GuardianDocumentAI


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
    """Run the hardened parser outside the web process."""

    from app.api.v1.bank_reconciliation_hardening import parse_bank_statement_only

    with open(file_item["path"], "rb") as handle:
        upload = UploadFile(file=handle, filename=file_item["filename"])
        return asyncio.run(
            parse_bank_statement_only(
                statement=upload,
                date_from=date_from,
                date_to=date_to,
            )
        )


def reconcile_bank_statement(
    organization_id: int,
    file_item: dict[str, str],
    *,
    date_from: str | None,
    date_to: str | None,
    company_id: int | None,
    bank_journal_id: int | None,
) -> dict[str, Any]:
    """Run the hardened full reconciliation and its audit trail in the worker."""

    from app.api.v1.bank_reconciliation_hardening import bank_reconciliation

    db = SessionLocal()
    try:
        with open(file_item["path"], "rb") as handle:
            upload = UploadFile(file=handle, filename=file_item["filename"])
            return asyncio.run(
                bank_reconciliation(
                    statement=upload,
                    db=db,
                    date_from=date_from,
                    date_to=date_to,
                    company_id=company_id,
                    bank_journal_id=bank_journal_id,
                )
            )
    finally:
        db.close()


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
