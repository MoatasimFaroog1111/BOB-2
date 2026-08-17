from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposalError
from app.services.accounting_human_reviewed_draft import AccountingHumanReviewedDraftService


class _DocumentReviewStub:
    def __init__(self, *, move_type: str = "entry"):
        self.move_type = move_type

    def analyze(self, **_kwargs):
        return {
            "status": "success",
            "source": {
                "filename": "safe-receipt.pdf",
                "mimetype": "application/pdf",
                "size_bytes": 16,
                "sha256": "abc123",
                "source_reference": "DOC-SHA256:abc123",
            },
            "prediction": {
                "model_version": "accounting-ml-v2.0.0",
                "bundle_sha256": "trusted-bundle",
                "confidence_proxy": 0.42,
                "move_type": [
                    {
                        "label": self.move_type,
                        "selected": True,
                        "model_score": 0.92,
                        "live_reference_resolved": False,
                    }
                ],
                "journals": [],
                "debit_accounts": [],
                "credit_accounts": [],
                "taxes": [],
                "analytic_accounts": [],
            },
            "decision_gate": {
                "draft_eligible": False,
                "review_required": True,
                "auto_post_allowed": False,
                "findings": [
                    {"code": "DEBIT_LOW_SCORE", "severity": "medium"},
                ],
            },
            "partner_candidates": [
                {
                    "id": 14,
                    "name": "Fahad Al-Baqmi",
                    "confidence": 0.40,
                    "live_reference_resolved": True,
                }
            ],
        }


class _ERPStub:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.created_move_vals = None
        self.created_attachment_vals = None

    @staticmethod
    def _domain(args):
        if not args:
            return []
        first = args[0]
        return first if isinstance(first, list) else []

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        kwargs = kwargs or {}

        if method == "search_read":
            domain = self._domain(args)
            if model == "res.company":
                return [{"id": 1, "name": "Company"}]
            if model == "account.journal":
                return [{
                    "id": 13,
                    "code": "BNK1",
                    "name": "Riyadh Bank",
                    "type": "bank",
                    "company_id": [1, "Company"],
                    "active": True,
                }]
            if model == "account.account":
                requested_id = int(domain[0][2])
                if requested_id == 104:
                    return [{
                        "id": 104,
                        "code": "201004",
                        "name": "Accrued - Salaries",
                        "company_ids": [1],
                        "deprecated": False,
                    }]
                if requested_id == 208:
                    return [{
                        "id": 208,
                        "code": "101001",
                        "name": "Riyadh Bank",
                        "company_ids": [1],
                        "deprecated": False,
                    }]
            if model == "res.partner":
                return [{
                    "id": 14,
                    "name": "Fahad Al-Baqmi",
                    "active": True,
                    "company_id": False,
                }]
            if model == "account.move":
                # Attachment adapter reads the newly created draft by ID; proposal
                # preflight/draft adapter query by deterministic ref and should see
                # no pre-existing move on the first pass.
                if any(item[:2] == ["id", "="] for item in domain if isinstance(item, list)):
                    return [{
                        "id": 23060,
                        "name": False,
                        "ref": "BOB-MLV2-test",
                        "state": "draft",
                        "company_id": [1, "Company"],
                    }]
                return []
            if model == "account.move.line":
                return [
                    {
                        "id": 79684,
                        "account_id": [104, "201004 Accrued - Salaries"],
                        "partner_id": [14, "Fahad Al-Baqmi"],
                        "debit": 5000.0,
                        "credit": 0.0,
                        "analytic_distribution": False,
                    },
                    {
                        "id": 79685,
                        "account_id": [208, "101001 Riyadh Bank"],
                        "partner_id": False,
                        "debit": 0.0,
                        "credit": 5000.0,
                        "analytic_distribution": False,
                    },
                ]
            if model == "ir.attachment":
                return []

        if model == "account.move" and method == "create":
            self.created_move_vals = dict(args[0])
            return 23060

        if model == "account.move" and method == "read":
            return [{
                "id": 23060,
                "name": False,
                "ref": self.created_move_vals["ref"],
                "state": "draft",
                "date": self.created_move_vals["date"],
                "journal_id": [13, "Riyadh Bank"],
                "company_id": [1, "Company"],
                "line_ids": [79684, 79685],
            }]

        if model == "ir.attachment" and method == "fields_get":
            return {
                "id": {"type": "integer"},
                "name": {"type": "char"},
                "type": {"type": "selection"},
                "datas": {"type": "binary"},
                "mimetype": {"type": "char"},
                "checksum": {"type": "char"},
                "file_size": {"type": "integer"},
                "company_id": {"type": "many2one"},
                "description": {"type": "text"},
                "res_model": {"type": "char"},
                "res_id": {"type": "integer"},
            }

        if model == "ir.attachment" and method == "create":
            self.created_attachment_vals = dict(args[0])
            return 14171

        if model == "ir.attachment" and method == "read":
            import hashlib

            raw = b"reviewed-pdf-data"
            return [{
                "id": 14171,
                "name": self.created_attachment_vals["name"],
                "mimetype": "application/pdf",
                "checksum": hashlib.sha1(raw).hexdigest(),
                "file_size": len(raw),
                "res_model": "account.move",
                "res_id": 23060,
            }]

        raise AssertionError(f"Unexpected ERP call: {model}.{method} args={args!r}")


def _catalog():
    return AccountingReferenceCatalog(
        accounts=(
            {
                "id": 104,
                "code": "201004",
                "name": "Accrued - Salaries",
                "account_type": "liability_current",
                "deprecated": False,
                "company_ids": [1],
            },
            {
                "id": 208,
                "code": "101001",
                "name": "Riyadh Bank",
                "account_type": "asset_cash",
                "deprecated": False,
                "company_ids": [1],
            },
        ),
        journals=(
            {
                "id": 13,
                "code": "BNK1",
                "name": "Riyadh Bank",
                "type": "bank",
                "active": True,
                "company_id": [1, "Company"],
            },
        ),
        partners=(
            {
                "id": 14,
                "name": "Fahad Al-Baqmi",
                "active": True,
                "company_id": False,
            },
        ),
    )


def test_human_review_can_override_blocked_gate_without_lowering_thresholds(monkeypatch):
    erp = _ERPStub()
    monkeypatch.setattr(
        "app.services.accounting_human_reviewed_draft.tenant_erp_resolver.resolve",
        lambda _db, _organization_id: (SimpleNamespace(provider="odoo"), erp),
    )
    monkeypatch.setattr(
        "app.services.accounting_human_reviewed_draft.OdooAccountingLearningSource.reference_catalog",
        lambda _self, *, company_id=None: _catalog(),
    )

    service = AccountingHumanReviewedDraftService(
        object(),
        document_review=_DocumentReviewStub(),
    )
    monkeypatch.setattr(service, "_audit", lambda **_kwargs: True)

    result = service.create(
        organization_id=1,
        company_id=1,
        filename="../../unsafe-receipt.pdf",
        mimetype="application/pdf",
        content=b"reviewed-pdf-data",
        amount="5000.00",
        entry_date="2026-08-09",
        description="Reviewed bank transfer",
        journal_id=13,
        debit_account_id=104,
        credit_account_id=208,
        debit_partner_id=14,
        reviewer={"user_id": 7, "role": "finance"},
    )

    assert result["status"] == "success"
    assert result["human_review_override"] is True
    assert result["original_decision_gate"]["draft_eligible"] is False
    assert result["safety"]["model_thresholds_changed"] is False
    assert result["safety"]["posting_method_invoked"] is False
    assert result["odoo_draft"]["state"] == "draft"
    assert result["attachment"]["attachment_id"] == 14171
    assert result["attachment"]["filename"] == "safe-receipt.pdf"

    line_commands = erp.created_move_vals["line_ids"]
    debit_vals = line_commands[0][2]
    credit_vals = line_commands[1][2]
    assert debit_vals["account_id"] == 104
    assert debit_vals["partner_id"] == 14
    assert debit_vals["debit"] == 5000.0
    assert "analytic_distribution" not in debit_vals
    assert credit_vals["account_id"] == 208
    assert "partner_id" not in credit_vals
    assert credit_vals["credit"] == 5000.0
    assert erp.created_attachment_vals["name"] == "safe-receipt.pdf"
    assert "action_post" not in [method for _model, method in erp.calls]


def test_human_review_refuses_non_entry_model_classification():
    service = AccountingHumanReviewedDraftService(
        object(),
        document_review=_DocumentReviewStub(move_type="in_invoice"),
    )

    with pytest.raises(AccountingDraftProposalError) as exc_info:
        service.create(
            organization_id=1,
            company_id=1,
            filename="invoice.pdf",
            mimetype="application/pdf",
            content=b"invoice-data",
            amount="115.00",
            entry_date="2026-08-09",
            description=None,
            journal_id=13,
            debit_account_id=104,
            credit_account_id=208,
        )

    assert exc_info.value.code == "MOVE_TYPE_REVIEW_WORKFLOW_REQUIRED"
