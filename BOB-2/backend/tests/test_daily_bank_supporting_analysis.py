from __future__ import annotations

from types import SimpleNamespace

from app.models.core import ApprovalRequest, AuditLog
from app.services.daily_bank_supporting_analysis import DailyBankSupportingAnalysisService


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is ApprovalRequest:
            return self.session.approval
        return None


class FakeSession:
    def __init__(self, approval):
        self.approval = approval
        self.added = []
        self.commits = 0

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1


def make_approval(extracted_amount="125.00"):
    return SimpleNamespace(
        id=22,
        organization_id=4,
        request_type="daily_bank_entry_audit",
        status="awaiting_human_approval",
        payload={
            "entry": {
                "lines": [
                    {
                        "role": "bank",
                        "source_amount": "-125.00",
                        "source_row": 3,
                    },
                    {
                        "role": "counterpart",
                        "source_amount": "-125.00",
                        "source_row": 3,
                    },
                ]
            },
            "supporting_documents": [
                {
                    "document_id": 8,
                    "filename": "invoice.pdf",
                    "analysis": {
                        "status": "analyzed",
                        "document_class": "invoice",
                        "fields": {"total_amount": extracted_amount, "supplier_name": "Vendor A"},
                    },
                }
            ],
            "audit_result": {
                "risk_level": "low",
                "recommendation": "approve",
                "blocking_count": 0,
                "warning_count": 0,
                "finding_count": 0,
                "findings": [],
            },
            "safe_to_post": False,
            "posting_performed": False,
        },
    )


def test_exact_supporting_amount_match_is_explainable_and_non_posting():
    approval = make_approval("125.00")
    db = FakeSession(approval)

    DailyBankSupportingAnalysisService().merge_semantic_findings_into_audit(
        db,
        organization_id=4,
        user_id=9,
        approval_id=22,
    )

    result = approval.payload["audit_result"]
    assert result["supporting_amount_match_count"] == 1
    assert result["supporting_semantic_warning_count"] == 0
    assert result["safe_to_post"] is False
    assert any(finding["code"] == "SUPPORTING_AMOUNT_MATCHED" for finding in result["findings"])
    assert any(isinstance(item, AuditLog) for item in db.added)


def test_nonmatching_supporting_amount_requires_human_review_not_silent_change():
    approval = make_approval("200.00")
    db = FakeSession(approval)

    DailyBankSupportingAnalysisService().merge_semantic_findings_into_audit(
        db,
        organization_id=4,
        user_id=9,
        approval_id=22,
    )

    result = approval.payload["audit_result"]
    assert result["warning_count"] == 1
    assert result["risk_level"] == "medium"
    assert result["recommendation"] == "human_review"
    assert any(finding["code"] == "SUPPORTING_AMOUNT_NOT_MATCHED" for finding in result["findings"])


def test_failed_local_document_analysis_becomes_review_warning():
    approval = make_approval()
    approval.payload["supporting_documents"][0]["analysis"] = {
        "status": "failed",
        "document_class": "unknown",
        "fields": {},
    }
    db = FakeSession(approval)

    DailyBankSupportingAnalysisService().merge_semantic_findings_into_audit(
        db,
        organization_id=4,
        user_id=9,
        approval_id=22,
    )

    result = approval.payload["audit_result"]
    assert result["warning_count"] == 1
    assert result["recommendation"] == "human_review"
    assert any(finding["code"] == "SUPPORTING_DOCUMENT_NOT_ANALYZED" for finding in result["findings"])
