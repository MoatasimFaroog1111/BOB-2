from __future__ import annotations

from app.erp.accounting_draft_adapter import OdooAccountingDraftAdapter
from app.ml.accounting_intelligence.draft_enrichment import AccountingDraftEnrichmentPolicy
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposalBuilder
from app.ml.accounting_intelligence.prediction_gate import AccountingPredictionGate


def _prediction(
    *,
    move_type: str = "entry",
    journal_type: str = "bank",
    tax_selected: bool = False,
    analytic_selected: bool = False,
    analytic_score: float = 0.91,
):
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
                "account_type": "expense",
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
                "account_type": "asset_cash",
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
        "analytic_accounts": [
            {
                "label": "Head Office",
                "id": 2,
                "model_score": analytic_score,
                "selected": analytic_selected,
                "rank": 1,
                "live_reference_resolved": True,
            }
        ],
    }


def _partner_candidates():
    return [
        {
            "id": 672,
            "name": "stc السعودية",
            "confidence": 0.93,
            "historical_consensus": 0.95,
            "evidence_strength": 0.98,
            "live_reference_resolved": True,
        }
    ]


def _proposal(*, enriched: bool = False):
    prediction = _prediction(analytic_selected=enriched)
    gate = AccountingPredictionGate().evaluate(prediction, amount=100.00)
    assert gate["draft_eligible"] is True
    partners = _partner_candidates() if enriched else []
    enrichment = AccountingDraftEnrichmentPolicy().resolve(
        prediction=prediction,
        partner_candidates=partners,
    )
    return AccountingDraftProposalBuilder().build(
        prediction=prediction,
        decision_gate=gate,
        amount="100.00",
        company_id=1,
        source_reference="document:abc123",
        entry_date="2026-08-16",
        description="Safe ML draft",
        partner_candidates=partners,
        enrichment=enrichment,
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


def test_proposal_keeps_unresolved_enrichment_empty():
    proposal = _proposal()
    assert proposal.move_type == "entry"
    assert proposal.journal_id == 13
    assert proposal.debit_line.account_id == 10
    assert proposal.credit_line.account_id == 20
    assert proposal.amount == "100.00"
    assert proposal.auto_post_allowed is False
    assert proposal.debit_line.partner_id is None
    assert proposal.debit_line.analytic_distribution == {}
    assert proposal.recommendations["not_auto_applied"] == [
        "partner",
        "analytic_distribution",
        "tax",
    ]
    assert proposal.idempotency_ref.startswith("BOB-MLV2-")


def test_enrichment_policy_applies_partner_and_analytic_only_to_non_bank_side():
    proposal = _proposal(enriched=True)
    assert proposal.debit_line.partner_id == 672
    assert proposal.debit_line.analytic_distribution == {"2": 100.0}
    assert proposal.credit_line.partner_id is None
    assert proposal.credit_line.analytic_distribution == {}
    applied = proposal.recommendations["enrichment_policy"]["auto_applied"]
    assert applied == ["partner", "analytic_distribution"]


def test_enrichment_policy_rejects_low_analytic_score():
    prediction = _prediction(analytic_selected=True, analytic_score=0.20)
    result = AccountingDraftEnrichmentPolicy().resolve(
        prediction=prediction,
        partner_candidates=_partner_candidates(),
    )
    assert result["debit_partner_id"] == 672
    assert result["debit_analytic_distribution"] == {}
    assert "analytic_distribution" in result["not_auto_applied"]


class _CreateERPStub:
    def __init__(self, proposal):
        self.proposal = proposal
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
                    "ref": self.proposal.idempotency_ref,
                    "state": "draft",
                    "date": "2026-08-16",
                    "journal_id": [13, "Bank"],
                    "company_id": [1, "Company"],
                    "line_ids": [901, 902],
                }
            ]
        if model == "account.move.line" and method == "search_read":
            return [
                {
                    "id": 901,
                    "account_id": [self.proposal.debit_line.account_id, "Debit"],
                    "partner_id": (
                        [self.proposal.debit_line.partner_id, "Partner"]
                        if self.proposal.debit_line.partner_id else False
                    ),
                    "debit": 100.0,
                    "credit": 0.0,
                    "analytic_distribution": self.proposal.debit_line.analytic_distribution or False,
                },
                {
                    "id": 902,
                    "account_id": [self.proposal.credit_line.account_id, "Credit"],
                    "partner_id": (
                        [self.proposal.credit_line.partner_id, "Partner"]
                        if self.proposal.credit_line.partner_id else False
                    ),
                    "debit": 0.0,
                    "credit": 100.0,
                    "analytic_distribution": self.proposal.credit_line.analytic_distribution or False,
                },
            ]
        raise AssertionError(f"Unexpected ERP call: {model}.{method}")


def test_odoo_adapter_creates_enriched_draft_and_has_no_posting_call():
    proposal = _proposal(enriched=True)
    erp = _CreateERPStub(proposal)
    result = OdooAccountingDraftAdapter(erp).create(proposal)
    assert result["created"] is True
    assert result["state"] == "draft"
    assert result["enrichment_verification"]["verified"] is True
    methods = [method for _model, method, _args, _kwargs in erp.calls]
    assert "action_post" not in methods


class _ExistingERPStub:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        if model == "account.move" and method == "search_read":
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
        if model == "account.move.line" and method == "search_read":
            return [
                {
                    "id": 911,
                    "account_id": [self.proposal.debit_line.account_id, "Debit"],
                    "partner_id": False,
                    "debit": 100.0,
                    "credit": 0.0,
                    "analytic_distribution": False,
                },
                {
                    "id": 912,
                    "account_id": [self.proposal.credit_line.account_id, "Credit"],
                    "partner_id": False,
                    "debit": 0.0,
                    "credit": 100.0,
                    "analytic_distribution": False,
                },
            ]
        raise AssertionError(f"Unexpected ERP call: {model}.{method}")


def test_odoo_adapter_reuses_existing_draft_idempotently():
    proposal = _proposal()
    erp = _ExistingERPStub(proposal)
    result = OdooAccountingDraftAdapter(erp).create(proposal)
    assert result["created"] is False
    assert result["idempotent_reuse"] is True
    assert result["move_id"] == 88
    assert erp.calls == [
        ("account.move", "search_read"),
        ("account.move.line", "search_read"),
    ]
