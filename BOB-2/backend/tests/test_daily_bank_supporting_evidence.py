from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.core import ApprovalRequest, AuditLog, Document, JournalEntryRecord
from app.services.daily_bank_supporting_evidence import DailyBankSupportingEvidenceService


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is ApprovalRequest:
            return self.session.approval
        if self.model is Document:
            return self.session.document
        if self.model is JournalEntryRecord:
            return self.session.journal_entry
        return None


class FakeSession:
    def __init__(self, approval):
        self.approval = approval
        self.document = None
        self.journal_entry = None
        self.added = []
        self.commits = 0

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, value):
        self.added.append(value)
        if isinstance(value, Document):
            if value.id is None:
                value.id = 501
            self.document = value

    def flush(self):
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        return None


def approval(status="pending_audit"):
    return SimpleNamespace(
        id=44,
        organization_id=9,
        request_type="daily_bank_entry_audit",
        status=status,
        payload={
            "journal_entry_id": 71,
            "entry": {"entry_date": "2026-08-10"},
            "supporting_documents": [],
            "safe_to_post": False,
            "posting_performed": False,
        },
    )


def test_supporting_document_is_tenant_persisted_hashed_and_sealed(tmp_path):
    row = approval()
    db = FakeSession(row)
    service = DailyBankSupportingEvidenceService(tmp_path)

    evidence = service.attach(
        db,
        organization_id=9,
        user_id=3,
        approval_id=44,
        filename="invoice.pdf",
        content_type="application/pdf",
        content=b"supporting-evidence",
    )

    assert evidence["document_id"] == 501
    assert len(evidence["sha256"]) == 64
    assert row.payload["supporting_documents"][0]["sha256"] == evidence["sha256"]
    assert row.payload["evidence_version"] == 1
    assert len(row.payload["package_hash"]) == 64
    assert row.payload["safe_to_post"] is False
    assert any(isinstance(item, AuditLog) for item in db.added)


def test_supporting_evidence_is_locked_after_audit_state(tmp_path):
    row = approval(status="awaiting_human_approval")
    db = FakeSession(row)
    service = DailyBankSupportingEvidenceService(tmp_path)

    with pytest.raises(HTTPException) as exc:
        service.attach(
            db,
            organization_id=9,
            user_id=3,
            approval_id=44,
            filename="invoice.pdf",
            content_type="application/pdf",
            content=b"supporting-evidence",
        )

    assert exc.value.status_code == 409


def test_supporting_hash_is_reverified_when_smart_audit_runs(tmp_path):
    row = approval()
    db = FakeSession(row)
    service = DailyBankSupportingEvidenceService(tmp_path)
    service.attach(
        db,
        organization_id=9,
        user_id=3,
        approval_id=44,
        filename="receipt.txt",
        content_type="text/plain",
        content=b"original-receipt",
    )
    row.status = "awaiting_human_approval"
    row.payload["audit_result"] = {
        "risk_level": "low",
        "recommendation": "approve",
        "blocking_count": 0,
        "warning_count": 0,
        "finding_count": 0,
        "checks_passed": True,
        "findings": [],
    }

    service.merge_verification_into_audit(
        db,
        organization_id=9,
        user_id=8,
        approval_id=44,
    )

    result = row.payload["audit_result"]
    assert result["supporting_evidence_verified_count"] == 1
    assert result["blocking_count"] == 0
    assert any(finding["code"] == "SUPPORTING_EVIDENCE_VERIFIED" for finding in result["findings"])


def test_tampered_supporting_document_blocks_approval(tmp_path):
    row = approval()
    db = FakeSession(row)
    service = DailyBankSupportingEvidenceService(tmp_path)
    service.attach(
        db,
        organization_id=9,
        user_id=3,
        approval_id=44,
        filename="approval.txt",
        content_type="text/plain",
        content=b"approved-original",
    )
    assert db.document is not None
    db.document.storage_path and open(db.document.storage_path, "wb").write(b"tampered")

    row.status = "awaiting_human_approval"
    row.payload["audit_result"] = {
        "risk_level": "low",
        "recommendation": "approve",
        "blocking_count": 0,
        "warning_count": 0,
        "finding_count": 0,
        "checks_passed": True,
        "findings": [],
    }

    service.merge_verification_into_audit(
        db,
        organization_id=9,
        user_id=8,
        approval_id=44,
    )

    result = row.payload["audit_result"]
    assert row.status == "needs_revision"
    assert result["blocking_count"] == 1
    assert result["risk_level"] == "high"
    assert any(
        finding["code"] == "SUPPORTING_EVIDENCE_INTEGRITY_FAILURE"
        for finding in result["findings"]
    )
