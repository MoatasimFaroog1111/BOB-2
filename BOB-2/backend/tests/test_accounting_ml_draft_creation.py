from __future__ import annotations

from app.erp.accounting_draft_adapter import OdooAccountingDraftAdapter
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposalBuilder
from app.ml.accounting_intelligence.prediction_gate import AccountingPredictionGate


def _prediction(*, move_type: str = "entry", journal_type: str = "bank", tax_selected: bool = False):
    return {
        "model_version": "accounting-ml-v2.0.0",
        "bundle_sha256": "trusted",
        "move_type": [
            {
                "label": move_type,
                "model_score": 0.95,
                "selected": True,
                "rank": 1,
                "live_reference_resolved": False,
            }
        ],
        "journals": [
            {
                "label": "BNK1",
                "code": "BNK1",
                "name": "Bank",
                "type": journal_type,
                "id": 13,
                "model_score": 0.91,
                "selected": True,
                "rank": 1,
                "live_reference_resolved": True,
            }
        ],
        "debit_accounts": [
            {
                "label": "400020",
                "code": "400020",
                "name": "Telephone And Internet",
                "id": 10,
                "model_score": 0.88,
                "selected": True,
                "rank": 1,
                "live_reference_resolved": True,
            }
        ],
        "credit_accounts": [
            {
                "label": "101001",
                "code": "101001",
                "name": "Bank",
                "id": 20,
                "model_score": 0.96,
                "selected": True,
                "rank": 1,
                "live_reference_resolved": True,
            }
        ],
        "taxes": [
            {
                "label": "15%",
                "id": 3,
                "model_score": 0.80,
                "selected": tax_selected,
                "rank": 1,
                "live_reference_resolved": True,
            }
        ],
        "analytic_accounts": [],
    }


def _proposal():
    prediction = _prediction()
    gate = AccountingPredictionGate().evaluate(prediction, amount=100.00)
    assert gate["draft_eligible"] is True
    return AccountingDraftProposalBuilder().build(
        prediction=prediction,
        decision_gate=gate,
        amount="100.00",
        company_id=1,
        source_reference="document:abc123",
        entry_date="2026-08-16",
        description="Safe ML draft",
    )


def test_gate_allows_only_simple_general_entry_draft():
    gate = AccountingPredictionGate().evaluate(_prediction(), amount=100.00)
    assert gate["draft_eligible"] is True
    assert gate["auto_post_allowed"] is False


def test_gate_rejects_vendor_bill_and_selected_tax_automation():
    invoice_gate = AccountingPredictionGate().evaluate(
        _prediction(move_type="in_invoice", journal_type="purchase"),
        amount=100.00,
    )
    assert invoice_gate["draft_eligible"] is False
    assert {row["code"] for row in invoice_gate["findings"]} >= {
        "MOVE_TYPE_REVIEW_ONLY",
        "JOURNAL_TYPE_REVIEW_ONLY",
    }

    tax_gate = AccountingPredictionGate().evaluate(
        _prediction(tax_selected=True),
        amount=115.00,
    )
    assert tax_gate["draft_eligible"] is False
    assert "TAX_AUTOMATION_REVIEW_ONLY" in {
        row["code"] for row in tax_gate["findings"]
    }


def test_proposal_is_minimal_and_keeps_risky_fields_as_recommendations():
    proposal = _proposal()
    assert proposal.move_type == "entry"
    assert proposal.journal_id == 13
    assert proposal.debit_line.account_id == 10
    assert proposal.credit_line.account_id == 20
    assert proposal.amount == "100.00"
    assert proposal.auto_post_allowed is False
    assert proposal.recommendations["not_auto_applied"] == [
        "partner",
        "analytic_account",
        "tax",
    ]
    assert proposal.idempotency_ref.startswith("BOB-MLV2-")


class _CreateERPStub:
    def __init__(self):
        self.calls = []

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        if model == "account.move" and method == "search_read":
            return []
        if model == "account.move" and method == "create":
            vals = args[0]
            assert vals["move_type"] == "entry"
            assert vals["ref"].startswith("BOB-MLV2-")
            assert len(vals["line_ids"]) == 2
            return 77
        if model == "account.move" and method == "read":
            return [
                {
                    "id": 77,
                    "name": "MISC/2026/00077",
                    "ref": _proposal().idempotency_ref,
                    "state": "draft",
                    "date": "2026-08-16",
                    "journal_id": [13, "Bank"],
                    "company_id": [1, "Company"],
                    "line_ids": [901, 902],
                }
            ]
        raise AssertionError(f"Unexpected ERP call: {model}.{method}")


def test_odoo_adapter_creates_draft_and_has_no_posting_call():
    erp = _CreateERPStub()
    result = OdooAccountingDraftAdapter(erp).create(_proposal())
    assert result["created"] is True
    assert result["state"] == "draft"
    methods = [method for _model, method, _args, _kwargs in erp.calls]
    assert "action_post" not in methods


class _ExistingERPStub:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        if method == "search_read":
            return [
                {
                    "id": 88,
                    "name": "MISC/2026/00088",
                    "ref": self.proposal.idempotency_ref,
                    "state": "draft",
                    "date": self.proposal.entry_date,
                    "journal_id": [13, "Bank"],
                    "company_id": [1, "Company"],
                }
            ]
        raise AssertionError(f"Unexpected ERP call: {model}.{method}")


def test_odoo_adapter_reuses_existing_draft_idempotently():
    proposal = _proposal()
    erp = _ExistingERPStub(proposal)
    result = OdooAccountingDraftAdapter(erp).create(proposal)
    assert result["created"] is False
    assert result["idempotent_reuse"] is True
    assert result["move_id"] == 88
    assert erp.calls == [("account.move", "search_read")]
