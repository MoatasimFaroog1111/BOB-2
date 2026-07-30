from __future__ import annotations

from app.api.v1.odoo_candidate_line_search import read_candidate_lines


class _FallbackERP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list, dict]] = []

    def execute_kw(self, model, method, args, kwargs):
        self.calls.append((model, method, args, kwargs))
        fields = kwargs.get("fields", [])
        if method == "search_read" and "restricted_dynamic_field" in fields:
            raise RuntimeError("restricted field")
        if method == "search_read":
            return [
                {
                    "id": 10,
                    "move_id": [20, "BNK1/2026/00010"],
                    "date": "2026-07-30",
                    "account_id": [30, "Bank"],
                    "partner_id": [40, "Supplier"],
                    "name": "Payment reference ABC",
                    "ref": "ABC",
                    "debit": 100.0,
                    "credit": 0.0,
                    "balance": 100.0,
                    "company_id": [1, "Company"],
                }
            ]
        raise AssertionError(f"Unexpected method: {method}")


class _SearchReadDeniedERP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list, dict]] = []

    def execute_kw(self, model, method, args, kwargs):
        self.calls.append((model, method, args, kwargs))
        if method == "search_read":
            raise RuntimeError("search_read rejected")
        if method == "search":
            return [10]
        if method == "read":
            return [
                {
                    "id": 10,
                    "move_id": [20, "BNK1/2026/00010"],
                    "date": "2026-07-30",
                    "account_id": [30, "Bank"],
                    "partner_id": [40, "Supplier"],
                    "name": "Payment reference ABC",
                    "ref": "ABC",
                    "debit": 100.0,
                    "credit": 0.0,
                    "balance": 100.0,
                    "company_id": [1, "Company"],
                }
            ]
        raise AssertionError(f"Unexpected method: {method}")


def _read(erp):
    return read_candidate_lines(
        erp,
        base_domain=[["company_id", "=", 1]],
        matched_partner_ids=[],
        terms=["ABC"],
        line_fields=[
            "id",
            "move_id",
            "date",
            "account_id",
            "partner_id",
            "name",
            "ref",
            "debit",
            "credit",
            "balance",
            "company_id",
            "restricted_dynamic_field",
        ],
        line_metadata={"name": {}, "ref": {}, "restricted_dynamic_field": {}},
        move_metadata={},
    )


def test_retries_with_safe_fields_when_dynamic_field_is_rejected():
    erp = _FallbackERP()
    result = _read(erp)

    assert result.successful_queries >= 1
    assert result.lines[0]["id"] == 10
    assert any(
        method == "search_read" and "restricted_dynamic_field" not in kwargs.get("fields", [])
        for _, method, _, kwargs in erp.calls
    )


def test_falls_back_to_search_then_read_when_search_read_is_rejected():
    erp = _SearchReadDeniedERP()
    result = _read(erp)

    assert result.successful_queries >= 1
    assert result.lines[0]["id"] == 10
    methods = [method for _, method, _, _ in erp.calls]
    assert "search" in methods
    assert "read" in methods
