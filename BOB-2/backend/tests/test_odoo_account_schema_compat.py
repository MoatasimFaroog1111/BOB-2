from __future__ import annotations

from app.erp.odoo_account_compat import (
    adapt_account_search_read_request,
    odoo_version_major,
    restore_account_search_read_response,
)


def test_version_major_reads_standard_odoo_payload():
    assert odoo_version_major({"server_version_info": [19, 0, 0, "final", 0]}) == 19
    assert odoo_version_major({"server_version": "18.0+e"}) == 18


def test_odoo19_rewrites_deprecated_to_active_without_mutating_input():
    args = [[("company_ids", "in", [1]), ("account_type", "=", "expense")]]
    kwargs = {"fields": ["id", "name", "code", "company_ids", "deprecated"], "limit": 1}

    adapted_args, adapted_kwargs, aliases = adapt_account_search_read_request(19, args, kwargs)

    assert args == [[("company_ids", "in", [1]), ("account_type", "=", "expense")]]
    assert kwargs["fields"][-1] == "deprecated"
    assert adapted_args == args
    assert adapted_kwargs["fields"] == ["id", "name", "code", "company_ids", "active"]
    assert aliases == {"deprecated": "active"}

    restored = restore_account_search_read_response(
        [{"id": 10, "name": "Expense", "code": "500001", "company_ids": [1], "active": True}],
        aliases,
    )
    assert restored[0]["active"] is True
    assert restored[0]["deprecated"] is False


def test_odoo19_rewrites_legacy_company_and_deprecated_fields_for_bank_posting():
    args = [[["id", "in", [10, 11]]]]
    kwargs = {"fields": ["id", "code", "name", "company_id", "deprecated"]}

    adapted_args, adapted_kwargs, aliases = adapt_account_search_read_request(19, args, kwargs)

    assert adapted_kwargs["fields"] == ["id", "code", "name", "company_ids", "active"]
    assert aliases == {"company_id": "company_ids", "deprecated": "active"}

    restored = restore_account_search_read_response(
        [{"id": 10, "code": "100001", "name": "Bank", "company_ids": [7], "active": True}],
        aliases,
    )
    assert restored == [
        {
            "id": 10,
            "code": "100001",
            "name": "Bank",
            "company_ids": [7],
            "company_id": 7,
            "active": True,
            "deprecated": False,
        }
    ]


def test_odoo19_rewrites_legacy_domain_semantics():
    args = [[
        ["company_id", "=", 7],
        ["deprecated", "=", False],
    ]]

    adapted_args, _kwargs, _aliases = adapt_account_search_read_request(19, args, {})

    assert adapted_args == [[
        ["company_ids", "=", 7],
        ["active", "=", True],
    ]]


def test_odoo18_keeps_deprecated_but_uses_company_ids():
    args = [[["company_id", "=", 7]]]
    kwargs = {"fields": ["id", "company_id", "deprecated"]}

    adapted_args, adapted_kwargs, aliases = adapt_account_search_read_request(18, args, kwargs)

    assert adapted_args == [[["company_ids", "=", 7]]]
    assert adapted_kwargs["fields"] == ["id", "company_ids", "deprecated"]
    assert aliases == {"company_id": "company_ids"}

    restored = restore_account_search_read_response(
        [{"id": 10, "company_ids": [7], "deprecated": False}],
        aliases,
    )
    assert restored[0]["company_id"] == 7
    assert restored[0]["deprecated"] is False
