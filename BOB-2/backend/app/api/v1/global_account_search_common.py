"""Shared functions for global Odoo account searches."""

from __future__ import annotations

from typing import Any

from app.api.v1.odoo_search_helpers import read_accounts
from app.api.v1.odoo_search_request import extract_global_search_request


def extract_global_request(prompt: str) -> str | None:
    return extract_global_search_request(prompt)


def read_account_map(
    erp: Any,
    account_ids: list[int],
) -> dict[int, dict[str, Any]]:
    return read_accounts(erp, account_ids)
