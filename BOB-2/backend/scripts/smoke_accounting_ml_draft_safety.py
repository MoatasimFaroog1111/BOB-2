#!/usr/bin/env python3
"""Runtime smoke for ML draft proposal + Odoo draft adapter safety.

Uses an in-memory ERP stub only. No network, Odoo mutation, training, or test-set
read occurs. The smoke proves gate policy, balanced draft construction,
idempotency, and absence of posting calls.
"""

from __future__ import annotations

from app.erp.accounting_draft_adapter import OdooAccountingDraftAdapter
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposalBuilder
from app.ml.accounting_intelligence.prediction_gate import AccountingPredictionGate


def prediction(*, move_type: str = "entry", journal_type: str = "bank", tax_selected: bool = False):
    return {
        "model_version": "accounting-ml-v2.0.0",
        "bundle_sha256": "runtime-smoke",
        "move_type": [{
            "label": move_type,
            "model_score": 0.97,
            "selected": True,
            "rank": 1,
            "live_reference_resolved": False,
        }],
        "journals": [{
            "label": "BNK1",
            "code": "BNK1",
            "name": "Bank",
            "type": journal_type,
            "id": 13,
            "model_score": 0.91,
            "selected": True,
            "rank": 1,
            "live_reference_resolved": True,
        }],
        "debit_accounts": [{
            "label": "400020",
            "code": "400020",
            "name": "Telephone And Internet",
            "id": 10,
            "model_score": 0.88,
            "selected": True,
            "rank": 1,
            "live_reference_resolved": True,
        }],
        "credit_accounts": [{
            "label": "101001",
            "code": "101001",
            "name": "Bank",
            "id": 20,
            "model_score": 0.96,
            "selected": True,
            "rank": 1,
            "live_reference_resolved": True,
        }],
        "taxes": [{
            "label": "15%",
            "id": 3,
            "model_score": 0.80,
            "selected": tax_selected,
            "rank": 1,
            "live_reference_resolved": True,
        }],
        "analytic_accounts": [],
    }


def build_proposal():
    pred = prediction()
    gate = AccountingPredictionGate().evaluate(pred, amount=100.00)
    assert gate["draft_eligible"] is True, gate
    assert gate["auto_post_allowed"] is False
    return AccountingDraftProposalBuilder().build(
        prediction=pred,
        decision_gate=gate,
        amount="100.00",
        company_id=1,
        source_reference="runtime-smoke:document-1",
        entry_date="2026-08-16",
        description="Runtime safety smoke",
    )


class ERPStub:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []
        self.existing = False

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        if model == "account.move" and method == "search_read":
            if self.existing:
                return [{
                    "id": 77,
                    "name": "MISC/2026/00077",
                    "ref": self.proposal.idempotency_ref,
                    "state": "draft",
                    "date": self.proposal.entry_date,
                    "journal_id": [13, "Bank"],
                    "company_id": [1, "Company"],
                }]
            return []
        if model == "account.move" and method == "create":
            vals = args[0]
            assert vals["move_type"] == "entry"
            assert vals["ref"] == self.proposal.idempotency_ref
            assert len(vals["line_ids"]) == 2
            debit = vals["line_ids"][0][2]
            credit = vals["line_ids"][1][2]
            assert debit["debit"] == credit["credit"] == 100.0
            assert debit["credit"] == credit["debit"] == 0.0
            self.existing = True
            return 77
        if model == "account.move" and method == "read":
            return [{
                "id": 77,
                "name": "MISC/2026/00077",
                "ref": self.proposal.idempotency_ref,
                "state": "draft",
                "date": self.proposal.entry_date,
                "journal_id": [13, "Bank"],
                "company_id": [1, "Company"],
                "line_ids": [901, 902],
            }]
        raise AssertionError(f"Unexpected call: {model}.{method}")


def main() -> int:
    invoice_gate = AccountingPredictionGate().evaluate(
        prediction(move_type="in_invoice", journal_type="purchase"),
        amount=100.00,
    )
    assert invoice_gate["draft_eligible"] is False

    tax_gate = AccountingPredictionGate().evaluate(
        prediction(tax_selected=True),
        amount=115.00,
    )
    assert tax_gate["draft_eligible"] is False

    proposal = build_proposal()
    assert proposal.auto_post_allowed is False
    assert proposal.recommendations["not_auto_applied"] == [
        "partner", "analytic_account", "tax"
    ]

    erp = ERPStub(proposal)
    adapter = OdooAccountingDraftAdapter(erp)
    first = adapter.create(proposal)
    second = adapter.create(proposal)

    assert first["created"] is True
    assert first["state"] == "draft"
    assert second["created"] is False
    assert second["idempotent_reuse"] is True
    methods = [method for _model, method in erp.calls]
    assert methods.count("create") == 1
    assert "action_post" not in methods

    print("GENERAL_ENTRY_ONLY_GATE=PASS")
    print("TAX_AUTOMATION_DISABLED=PASS")
    print("BALANCED_TWO_LINE_PROPOSAL=PASS")
    print("ODOO_DRAFT_STATE_VERIFIED=PASS")
    print("IDEMPOTENCY_REUSE=PASS")
    print("ACTION_POST_NOT_CALLED=PASS")
    print("ERP_NETWORK_MUTATION_DURING_SMOKE=FALSE")
    print("ACCOUNTING_ML_DRAFT_SAFETY_SMOKE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
