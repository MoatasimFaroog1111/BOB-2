"""Local accounting analysis for supporting documents in daily bank audit packages.

This service intentionally uses the application's local document-processing boundary and
stores only structured accounting fields in the review package. It does not send document
text or files to an external LLM. Semantic checks are evidence for a human reviewer, not
posting authority.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.erp.document_ai import GuardianDocumentAI
from app.models.core import ApprovalRequest, AuditLog, Document, JournalEntryRecord


REVIEW_REQUEST_TYPE = "daily_bank_entry_audit"
_SAFE_FIELD_NAMES = frozenset({
    "document_class",
    "invoice_number",
    "reference",
    "invoice_date",
    "date",
    "processing_date",
    "payment_date",
    "transaction_date",
    "total_amount",
    "amount_total",
    "amount",
    "total",
    "grand_total",
    "payment_amount",
    "supplier_name",
    "vendor_name",
    "partner_name",
    "customer_name",
    "company_name",
    "vat_number",
    "tax_number",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _seal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    mutable = dict(payload)
    mutable.pop("package_hash", None)
    mutable.pop("audit_result", None)
    mutable["evidence_version"] = int(mutable.get("evidence_version") or 0) + 1
    mutable["evidence_updated_at"] = _utc_now_iso()
    mutable["safe_to_post"] = False
    mutable["posting_performed"] = False
    return {**mutable, "package_hash": _canonical_hash(mutable)}


def _amount(value: Any) -> Decimal | None:
    if value in (None, "", False):
        return None
    try:
        return abs(Decimal(str(value).replace(",", "")).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return None


class DailyBankSupportingAnalysisService:
    @staticmethod
    def _approval(db: Session, organization_id: int, approval_id: int) -> ApprovalRequest:
        row = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.request_type == REVIEW_REQUEST_TYPE,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Daily bank audit package not found.")
        return row

    @staticmethod
    def _document(db: Session, organization_id: int, document_id: int) -> Document:
        row = (
            db.query(Document)
            .filter(Document.id == document_id, Document.organization_id == organization_id)
            .first()
        )
        if not row or row.classification != "bank_review_supporting":
            raise HTTPException(status_code=404, detail="Supporting document not found.")
        return row

    @staticmethod
    def _audit_log(
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        approval_id: int,
        action: str,
        details: dict[str, Any],
    ) -> None:
        db.add(AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            entity_type="approval_request",
            entity_id=str(approval_id),
            details=details,
        ))

    def analyze_attached_document(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        approval_id: int,
        document_id: int,
    ) -> dict[str, Any]:
        approval = self._approval(db, organization_id, approval_id)
        payload = dict(approval.payload or {})
        supporting = [dict(item) for item in (payload.get("supporting_documents") or [])]
        target_index = next(
            (index for index, item in enumerate(supporting) if int(item.get("document_id") or 0) == document_id),
            None,
        )
        if target_index is None:
            raise HTTPException(status_code=404, detail="Supporting document is not part of this audit package.")
        document = self._document(db, organization_id, document_id)

        try:
            result = GuardianDocumentAI().analyze_document(document.storage_path)
            fields = result.get("fields") or {}
            structured = {
                key: fields.get(key)
                for key in _SAFE_FIELD_NAMES
                if fields.get(key) not in (None, "", False)
            }
            analysis = {
                "status": "analyzed",
                "document_class": str(result.get("document_class") or fields.get("document_class") or "unknown"),
                "fields": structured,
                "analyzed_at": _utc_now_iso(),
                "analysis_method": "local_document_ai_structured_fields",
                "external_llm_used": False,
            }
        except Exception as exc:
            analysis = {
                "status": "failed",
                "document_class": "unknown",
                "fields": {},
                "analyzed_at": _utc_now_iso(),
                "analysis_method": "local_document_ai_structured_fields",
                "external_llm_used": False,
                "error": str(exc)[:500],
            }

        supporting[target_index]["analysis"] = analysis
        payload["supporting_documents"] = supporting
        approval.payload = _seal_payload(payload)
        self._audit_log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            approval_id=approval_id,
            action="daily_bank_review.supporting_evidence_analyzed",
            details={
                "document_id": document_id,
                "analysis_status": analysis["status"],
                "document_class": analysis["document_class"],
                "external_llm_used": False,
                "package_hash": approval.payload.get("package_hash"),
            },
        )
        db.commit()
        return analysis

    @staticmethod
    def _source_transaction_amounts(payload: dict[str, Any]) -> set[Decimal]:
        values: set[Decimal] = set()
        for line in ((payload.get("entry") or {}).get("lines") or []):
            if str(line.get("role") or "") != "bank":
                continue
            parsed = _amount(line.get("source_amount"))
            if parsed is not None:
                values.add(parsed)
        return values

    @staticmethod
    def _analysis_amount(analysis: dict[str, Any]) -> Decimal | None:
        fields = analysis.get("fields") or {}
        for name in (
            "total_amount",
            "amount_total",
            "amount",
            "total",
            "grand_total",
            "payment_amount",
        ):
            parsed = _amount(fields.get(name))
            if parsed is not None:
                return parsed
        return None

    def merge_semantic_findings_into_audit(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        approval_id: int,
    ) -> None:
        approval = self._approval(db, organization_id, approval_id)
        payload = dict(approval.payload or {})
        audit_result = dict(payload.get("audit_result") or {})
        if not audit_result:
            raise HTTPException(status_code=409, detail="Smart Audit must run before document analysis findings are merged.")

        findings = list(audit_result.get("findings") or [])
        transaction_amounts = self._source_transaction_amounts(payload)
        supporting = list(payload.get("supporting_documents") or [])
        semantic_warnings = 0
        amount_matches = 0
        analyzed_count = 0

        for item in supporting:
            analysis = dict(item.get("analysis") or {})
            filename = str(item.get("filename") or "supporting document")
            if analysis.get("status") != "analyzed":
                semantic_warnings += 1
                findings.append({
                    "severity": "warning",
                    "code": "SUPPORTING_DOCUMENT_NOT_ANALYZED",
                    "title": "Supporting document could not be analyzed automatically",
                    "reason": "The document remains available to the human reviewer, but structured accounting fields could not be extracted locally.",
                    "evidence": {
                        "document_id": item.get("document_id"),
                        "filename": filename,
                        "analysis_status": analysis.get("status") or "missing",
                    },
                    "suggested_action": "Open the supporting document and verify it manually before approval.",
                    "source_row": None,
                })
                continue

            analyzed_count += 1
            support_amount = self._analysis_amount(analysis)
            if support_amount is None:
                findings.append({
                    "severity": "info",
                    "code": "SUPPORTING_DOCUMENT_NO_AMOUNT_EXTRACTED",
                    "title": "No monetary total was extracted from a supporting document",
                    "reason": "This may be normal for approvals, correspondence, or non-monetary evidence.",
                    "evidence": {
                        "document_id": item.get("document_id"),
                        "filename": filename,
                        "document_class": analysis.get("document_class"),
                    },
                    "suggested_action": "Review the document content and determine whether it supports the transaction purpose.",
                    "source_row": None,
                })
                continue

            if support_amount in transaction_amounts:
                amount_matches += 1
                findings.append({
                    "severity": "info",
                    "code": "SUPPORTING_AMOUNT_MATCHED",
                    "title": "Supporting document amount matches a bank transaction",
                    "reason": "The locally extracted document total exactly matches one transaction amount in the daily bank entry.",
                    "evidence": {
                        "document_id": item.get("document_id"),
                        "filename": filename,
                        "document_class": analysis.get("document_class"),
                        "extracted_amount": str(support_amount),
                    },
                    "suggested_action": "Confirm the business purpose, counterparty, date, and authorization before human approval.",
                    "source_row": None,
                })
            else:
                semantic_warnings += 1
                findings.append({
                    "severity": "warning",
                    "code": "SUPPORTING_AMOUNT_NOT_MATCHED",
                    "title": "Supporting document amount does not match a bank transaction",
                    "reason": "The locally extracted document total was not found among the individual source transaction amounts for this daily entry.",
                    "evidence": {
                        "document_id": item.get("document_id"),
                        "filename": filename,
                        "document_class": analysis.get("document_class"),
                        "extracted_amount": str(support_amount),
                    },
                    "suggested_action": "Check whether the document relates to multiple payments, partial settlement, VAT/withholding differences, or the wrong daily entry.",
                    "source_row": None,
                })

        audit_result["warning_count"] = int(audit_result.get("warning_count") or 0) + semantic_warnings
        audit_result["finding_count"] = len(findings)
        audit_result["findings"] = findings
        audit_result["supporting_documents_analyzed_count"] = analyzed_count
        audit_result["supporting_amount_match_count"] = amount_matches
        audit_result["supporting_semantic_warning_count"] = semantic_warnings
        audit_result["supporting_semantic_checked_at"] = _utc_now_iso()
        audit_result["safe_to_post"] = False
        if int(audit_result.get("blocking_count") or 0) == 0 and semantic_warnings:
            audit_result["risk_level"] = "medium"
            audit_result["recommendation"] = "human_review"

        payload["audit_result"] = audit_result
        payload["safe_to_post"] = False
        payload["posting_performed"] = False
        approval.payload = payload
        self._audit_log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            approval_id=approval_id,
            action="daily_bank_review.supporting_semantic_audit_completed",
            details={
                "supporting_document_count": len(supporting),
                "analyzed_count": analyzed_count,
                "amount_match_count": amount_matches,
                "semantic_warning_count": semantic_warnings,
                "external_llm_used": False,
            },
        )
        db.commit()


daily_bank_supporting_analysis_service = DailyBankSupportingAnalysisService()
