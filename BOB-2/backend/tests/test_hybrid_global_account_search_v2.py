from __future__ import annotations

import inspect

from app.api.v1.hybrid_global_account_search_v2 import (
    SearchDiagnostics,
    _read_candidate_lines,
    _search_terms,
)


class FakeERP:
    def __init__(self) -> None:
        self.domains: list[list[object]] = []

    def execute_kw(self, model, method, args, kwargs=None):
        assert model == "account.move.line"
        assert method == "search_read"
        domain = args[0]
        self.domains.append(domain)

        if any(
            isinstance(leaf, list)
            and leaf
            and leaf[0] == "move_id.narration"
            for leaf in domain
        ):
            raise RuntimeError("optional related field rejected")

        if any(
            isinstance(leaf, list)
            and leaf
            and leaf[0] == "partner_id"
            for leaf in domain
        ):
            return [
                {
                    "id": 10,
                    "move_id": [20, "BNK1/2025/00001"],
                    "date": "2025-01-01",
                    "account_id": [30, "102014 Other Receivable"],
                    "partner_id": [1, "Ghulam Hussain"],
                    "name": "Payment to Ghulam",
                    "ref": "GHULAM",
                    "debit": 100.0,
                    "credit": 0.0,
                }
            ]

        return []


def test_candidate_search_is_filtered_and_fail_soft() -> None:
    erp = FakeERP()
    diagnostics = SearchDiagnostics()
    line_metadata = {
        "id": {"type": "integer"},
        "move_id": {"type": "many2one"},
        "date": {"type": "date"},
        "account_id": {"type": "many2one"},
        "partner_id": {"type": "many2one"},
        "name": {"type": "char"},
        "ref": {"type": "char"},
        "debit": {"type": "monetary"},
        "credit": {"type": "monetary"},
        "company_id": {"type": "many2one"},
    }
    move_metadata = {
        "ref": {"type": "char"},
        "payment_reference": {"type": "char"},
        "narration": {"type": "html"},
    }

    rows = _read_candidate_lines(
        erp,
        company_id=1,
        matched_partner_ids=[1],
        terms=["غلام", "ghlam", "Ghulam"],
        line_fields=list(line_metadata),
        line_metadata=line_metadata,
        move_metadata=move_metadata,
        diagnostics=diagnostics,
    )

    assert [row["id"] for row in rows] == [10]
    assert diagnostics.successful_queries >= 1
    assert diagnostics.skipped_queries == 1
    assert all(domain for domain in erp.domains)
    assert all(
        any(
            isinstance(leaf, list)
            and leaf
            and leaf[0] in {
                "company_id",
                "partner_id",
                "name",
                "ref",
                "move_id.ref",
                "move_id.payment_reference",
                "move_id.narration",
            }
            for leaf in domain
        )
        for domain in erp.domains
    )


def test_search_terms_reuse_observed_ghulam_spelling() -> None:
    terms = _search_terms("غلام", ["GHULAM HUSSAIN"])

    assert "غلام" in terms
    assert any(term.casefold() == "ghulam" for term in terms)


def test_v2_never_imports_full_ledger_reader_or_dynamic_domain_builder() -> None:
    import app.api.v1.hybrid_global_account_search_v2 as module

    source = inspect.getsource(module)

    assert "_read_account_lines" not in source
    assert "_direct_text_fields" not in source
    assert "search_count" not in source


def test_router_uses_resilient_v2() -> None:
    import app.api.v1.accounting_command_router as router_module

    source = inspect.getsource(router_module)

    assert "try_hybrid_global_account_search_v2" in source
    assert "try_hybrid_global_account_search(" not in source
