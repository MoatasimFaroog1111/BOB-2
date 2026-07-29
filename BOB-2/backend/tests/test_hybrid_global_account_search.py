from __future__ import annotations

import ast
import inspect

from app.api.v1.hybrid_global_account_search import (
    MAX_CANDIDATE_LINES,
    _candidate_domain,
    _direct_search_terms,
    _extract_global_request,
    _or_domain,
)


def test_screenshot_prompt_routes_to_local_global_search() -> None:
    prompt = (
        "ابحث مباشرة في Odoo في جميع الحسابات واجلب لي جميع البيانات "
        "المرتبطة بالكلمة غلام سواء بالعربي ام بالانجليزي او أي كلمة قريبة منها"
    )

    assert _extract_global_request(prompt) == "غلام"


def test_all_accounts_english_prompt_is_supported() -> None:
    assert (
        _extract_global_request(
            "Search all accounts for the partner Ghulam and similar spellings"
        )
        == "Ghulam"
    )


def test_account_scoped_prompt_stays_with_account_route() -> None:
    prompt = "اجلب من الحساب 102014 كل العمليات المرتبطة بالكلمة غلام"

    assert _extract_global_request(prompt) is None


def test_unscoped_general_chat_does_not_trigger_global_odoo_scan() -> None:
    assert _extract_global_request("ما معنى حساب المصروفات؟") is None


def test_global_search_module_has_no_external_ai_import() -> None:
    import app.api.v1.hybrid_global_account_search as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    assert imported_modules.isdisjoint({"anthropic", "openai", "ollama"})


def test_global_search_does_not_download_all_account_lines() -> None:
    import app.api.v1.hybrid_global_account_search as module

    source = inspect.getsource(module)

    assert "_read_account_lines" not in source
    assert MAX_CANDIDATE_LINES == 5_000


def test_discovered_partner_spelling_becomes_odoo_search_term() -> None:
    terms = _direct_search_terms("غلام", ["GHULAM HUSSAIN Insurance"])

    assert "غلام" in terms
    assert "GHULAM" in terms
    assert len(terms) <= 20


def test_candidate_domain_prefilters_by_partner_and_text() -> None:
    domain = _candidate_domain(
        company_id=1,
        matched_partner_ids=[77],
        search_terms=["غلام", "GHULAM"],
        line_metadata={
            "name": {"type": "char", "string": "Label"},
            "ref": {"type": "char", "string": "Reference"},
        },
        move_metadata={
            "ref": {"type": "char", "string": "Reference"},
            "payment_reference": {
                "type": "char",
                "string": "Payment Reference",
            },
        },
    )

    assert domain[0] == ["company_id", "=", 1]
    assert ["partner_id", "in", [77]] in domain
    assert ["name", "ilike", "GHULAM"] in domain
    assert ["move_id.payment_reference", "ilike", "غلام"] in domain


def test_empty_candidate_domain_never_triggers_full_scan() -> None:
    assert (
        _candidate_domain(
            company_id=1,
            matched_partner_ids=[],
            search_terms=[],
            line_metadata={},
            move_metadata={},
        )
        == []
    )


def test_odoo_or_domain_prefix_is_valid() -> None:
    conditions = [
        ["partner_id", "in", [1]],
        ["name", "ilike", "Ghulam"],
        ["ref", "ilike", "غلام"],
    ]

    assert _or_domain(conditions) == ["|", "|", *conditions]
