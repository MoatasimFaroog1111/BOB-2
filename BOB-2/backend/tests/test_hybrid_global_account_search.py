from __future__ import annotations

from app.api.v1.global_account_search_common import extract_global_request
from app.api.v1.odoo_candidate_line_search import (
    MAX_CANDIDATE_LINES,
    or_terms,
    read_candidate_lines,
)
from app.api.v1.odoo_search_request import extract_account_search_request


def test_screenshot_prompt_routes_to_local_global_search() -> None:
    prompt = (
        "ابحث مباشرة في Odoo في جميع الحسابات واجلب لي جميع البيانات "
        "المرتبطة بالكلمة غلام سواء بالعربي ام بالانجليزي او أي كلمة قريبة منها"
    )

    assert extract_global_request(prompt) == "غلام"


def test_all_accounts_english_prompt_is_supported() -> None:
    assert (
        extract_global_request(
            "Search all accounts for the partner Ghulam and similar spellings"
        )
        == "Ghulam"
    )


def test_account_scoped_prompt_stays_with_account_route() -> None:
    prompt = "اجلب من الحساب 102014 كل العمليات المرتبطة بالكلمة غلام"

    assert extract_global_request(prompt) is None
    assert extract_account_search_request(prompt) == ("102014", "غلام")


def test_unscoped_general_chat_does_not_trigger_global_odoo_scan() -> None:
    assert extract_global_request("ما معنى حساب المصروفات؟") is None


def test_candidate_limit_remains_bounded() -> None:
    assert MAX_CANDIDATE_LINES == 5_000


def test_odoo_or_domain_prefix_is_valid() -> None:
    assert or_terms("name", ["Ghulam", "غلام"]) == [
        "|",
        ["name", "ilike", "Ghulam"],
        ["name", "ilike", "غلام"],
    ]


class RecordingERP:
    def __init__(self) -> None:
        self.domains: list[list[object]] = []

    def execute_kw(self, model, method, args, kwargs=None):
        assert model == "account.move.line"
        assert method == "search_read"
        self.domains.append(args[0])
        return []


def test_account_candidate_search_never_loses_account_filter() -> None:
    erp = RecordingERP()
    result = read_candidate_lines(
        erp,
        base_domain=[
            ["account_id", "in", [77]],
            ["company_id", "=", 1],
        ],
        matched_partner_ids=[9],
        terms=["Ghulam"],
        line_fields=["id", "account_id", "partner_id", "name", "ref"],
        line_metadata={"name": {"type": "char"}, "ref": {"type": "char"}},
        move_metadata={"ref": {"type": "char"}},
    )

    assert result.successful_queries >= 1
    assert erp.domains
    assert all(["account_id", "in", [77]] in domain for domain in erp.domains)
    assert all(["company_id", "=", 1] in domain for domain in erp.domains)
