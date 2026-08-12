"""Supporting-document evidence for the daily bank audit workflow.

Evidence may be added only before the audit decision is finalized. Files are persisted in
a tenant-isolated store, hashed, sealed into the ApprovalRequest payload and re-verified
when Smart Auditor runs. This component never mutates accounting lines or posts to ERP.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import ApprovalRequest, AuditLog, Document, JournalEntryRecord


REVIEW_REQUEST_TYPE = "daily_bank_entry_audit"
_EDITABLE_EVIDENCE_STATES = frozenset({"pending_audit", "needs_revision"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DailyBankSupportingEvidenceService:
    def __init__(self, storage_root: str | Path | None = None) -> None:
        self._root = Path(storage_root or settings.STORAGE_DIR).resolve()

    def _tenant_dir(self, organization_id: int) -> Path:
        path = (self._root / "daily-bank-review" / f"org-{organization_id}").resolve()
        if not path.is_relative_to(self._root):
            raise HTTPException(status_code=400, detail="Invalid supporting evidence path.")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _approval(db: Session, organization_id: int, approval_id: int) -> ApprovalRequest:
        approval = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.request_type == REVIEW_REQUEST_TYPE,
            )
            .first()
        )
        if not approval:
            raise HTTPException(status_code=404, detail="Daily bank audit package not found.")
        return approval

    @staticmethod
    def _audit_log(
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        action: str,
        approval_id: int,
        details: dict[str, Any],
    ) -> None:
        db.add(
            AuditLog(
                organization_id=organization_id,
                user_id=user_id,
                action=action,
                entity_type="approval_request",
                entity_id=str(approval_id),
                details=details,
            )
        )

    def _path_for_document(self, document: Document, organization_id: int) -> Path:
        if document.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Supporting document not found.")
        target = Path(document.storage_path).resolve()
        tenant_root = self._tenant_dir(organization_id)
        if not target.is_relative_to(tenant_root) or not target.is_file():
            raise HTTPException(status_code=404, detail="Supporting document evidence is unavailable.")
        return target

    @staticmethod
    def _seal_payload(payload: dict[str, Any]) -> dict[str, Any]:
        mutable = dict(payload)
        mutable.pop("package_hash", None)
        mutable.pop("audit_result", None)
        mutable["evidence_version"] = int(mutable.get("evidence_version") or 0) + 1
        mutable["evidence_updated_at"] = _utc_now_iso()
        mutable["safe_to_post"] = False
        mutable["posting_performed"] = False
        package_hash = _canonical_hash(mutable)
        return {**mutable, "package_hash": package_hash}

    def attach(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        approval_id: int,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> dict[str, Any]:
        if not content:
            raise HTTPException(status_code=400, detail="Supporting document is empty.")
        approval = self._approval(db, organization_id, approval_id)
        if approval.status not in _EDITABLE_EVIDENCE_STATES:
            raise HTTPException(
                status_code=409,
                detail="Supporting evidence is locked after Smart Audit has completed. Return the package for revision before adding evidence.",
            )

        suffix = Path(filename).suffix.lower()
        target = (
            self._tenant_dir(organization_id)
            / f"support-{approval_id}-{uuid.uuid4().hex}{suffix}"
        ).resolve()
        if not target.is_relative_to(self._tenant_dir(organization_id)):
            raise HTTPException(status_code=400, detail="Invalid supporting evidence path.")
        target.write_bytes(content)
        sha256 = hashlib.sha256(content).hexdigest()

        document = Document(
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename=filename,
            content_type=content_type,
            storage_path=str(target),
            status="audit_evidence",
            classification="bank_review_supporting",
        )
        db.add(document)
        db.flush()

        evidence = {
            "document_id": document.id,
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "size": len(content),
            "sha256": sha256,
            "classification": "bank_review_supporting",
            "attached_by_user_id": user_id,
            "attached_at": _utc_now_iso(),
        }
        payload = dict(approval.payload or {})
        supporting = list(payload.get("supporting_documents") or [])
        supporting.append(evidence)
        payload["supporting_documents"] = supporting
        approval.payload = self._seal_payload(payload)

        self._audit_log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="daily_bank_review.supporting_evidence_attached",
            approval_id=approval_id,
            details={
                "document_id": document.id,
                "filename": filename,
                "sha256": sha256,
                "size": len(content),
                "evidence_version": approval.payload.get("evidence_version"),
                "package_hash": approval.payload.get("package_hash"),
            },
        )
        try:
            db.commit()
        except Exception:
            db.rollback()
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        return evidence

    def list(self, db: Session, *, organization_id: int, approval_id: int) -> list[dict[str, Any]]:
        approval = self._approval(db, organization_id, approval_id)
        return list((approval.payload or {}).get("supporting_documents") or [])

    def document_path(
        self,
        db: Session,
        *,
        organization_id: int,
        approval_id: int,
        document_id: int,
    ) -> tuple[Document, Path]:
        approval = self._approval(db, organization_id, approval_id)
        allowed_ids = {
            int(item.get("document_id") or 0)
            for item in ((approval.payload or {}).get("supporting_documents") or [])
        }
        if document_id not in allowed_ids:
            raise HTTPException(status_code=404, detail="Supporting document not found in this audit package.")
        document = (
            db.query(Document)
            .filter(Document.id == document_id, Document.organization_id == organization_id)
            .first()
        )
        if not document or document.classification != "bank_review_supporting":
            raise HTTPException(status_code=404, detail="Supporting document not found.")
        return document, self._path_for_document(document, organization_id)

    def merge_verification_into_audit(
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
            raise HTTPException(status_code=409, detail="Core Smart Audit must run before evidence verification.")

        findings = list(audit_result.get("findings") or [])
        supporting = list(payload.get("supporting_documents") or [])
        evidence_errors = 0
        verified = 0
        for item in supporting:
            document_id = int(item.get("document_id") or 0)
            document = (
                db.query(Document)
                .filter(Document.id == document_id, Document.organization_id == organization_id)
                .first()
            )
            actual_hash = ""
            if document:
                try:
                    path = self._path_for_document(document, organization_id)
                    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                except HTTPException:
                    actual_hash = ""
            if not actual_hash or actual_hash != str(item.get("sha256") or ""):
                evidence_errors += 1
                findings.append({
                    "severity": "error",
                    "code": "SUPPORTING_EVIDENCE_INTEGRITY_FAILURE",
                    "title": "Supporting document integrity check failed",
                    "reason": "A supporting document is missing or no longer matches the SHA-256 hash sealed into the audit package.",
                    "evidence": {
                        "document_id": document_id,
                        "filename": item.get("filename"),
                        "expected_sha256": item.get("sha256"),
                        "actual_sha256": actual_hash or None,
                    },
                    "suggested_action": "Stop approval, restore the original evidence, and resubmit the package.",
                    "source_row": None,
                })
            else:
                verified += 1

        if supporting and evidence_errors == 0:
            findings.append({
                "severity": "info",
                "code": "SUPPORTING_EVIDENCE_VERIFIED",
                "title": "Supporting document evidence verified",
                "reason": "All attached supporting documents match the SHA-256 hashes sealed into the audit package.",
                "evidence": {"verified_document_count": verified},
                "suggested_action": "Review the document contents against the related journal lines before human approval.",
                "source_row": None,
            })
        elif not supporting:
            findings.append({
                "severity": "info",
                "code": "NO_ADDITIONAL_SUPPORTING_EVIDENCE",
                "title": "No additional supporting documents were attached",
                "reason": "The original bank statement remains the primary source evidence. Additional evidence may be unnecessary for some bank-originated items, but the reviewer should assess whether more support is required.",
                "evidence": {"supporting_document_count": 0},
                "suggested_action": "If the business purpose requires invoices, receipts, approvals, or other support, return the package and attach them before approval.",
                "source_row": None,
            })

        original_blocking = int(audit_result.get("blocking_count") or 0)
        audit_result["blocking_count"] = original_blocking + evidence_errors
        audit_result["finding_count"] = len(findings)
        audit_result["findings"] = findings
        audit_result["supporting_evidence_count"] = len(supporting)
        audit_result["supporting_evidence_verified_count"] = verified
        audit_result["supporting_evidence_checked_at"] = _utc_now_iso()
        audit_result["safe_to_post"] = False
        if evidence_errors:
            audit_result["risk_level"] = "high"
            audit_result["recommendation"] = "needs_revision"
            audit_result["checks_passed"] = False
            approval.status = "needs_revision"
            journal_entry_id = int(payload.get("journal_entry_id") or 0)
            record = (
                db.query(JournalEntryRecord)
                .filter(
                    JournalEntryRecord.id == journal_entry_id,
                    JournalEntryRecord.organization_id == organization_id,
                )
                .first()
            )
            if record:
                record.status = "needs_revision"

        payload["audit_result"] = audit_result
        payload["safe_to_post"] = False
        payload["posting_performed"] = False
        approval.payload = payload
        self._audit_log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="daily_bank_review.supporting_evidence_verified",
            approval_id=approval_id,
            details={
                "supporting_document_count": len(supporting),
                "verified_count": verified,
                "integrity_failure_count": evidence_errors,
                "blocking_count": audit_result["blocking_count"],
            },
        )
        db.commit()


daily_bank_supporting_evidence_service = DailyBankSupportingEvidenceService()
