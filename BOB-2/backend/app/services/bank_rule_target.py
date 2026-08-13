"""Canonical Bank Rule target normalization."""
from __future__ import annotations
from typing import Any, Mapping

TAX_AMOUNT_MODE_INCLUDED = "included_in_bank_amount"


def normalize_bank_rule_target(target: Mapping[str, Any]) -> dict[str, Any]:
    account_id = int(target.get("account_id") or 0) or None
    tax_id = int(target.get("tax_id") or 0) or None
    tax_amount_mode = str(target.get("tax_amount_mode") or "").strip() or (
        TAX_AMOUNT_MODE_INCLUDED if tax_id else None
    )
    if tax_amount_mode not in (None, TAX_AMOUNT_MODE_INCLUDED):
        raise ValueError(f"Unsupported Bank Rule tax amount mode: {tax_amount_mode}")
    return {
        "account_id": account_id,
        "account_code": str(target.get("account_code") or ""),
        "account_name": str(target.get("account_name") or ""),
        "partner_id": int(target.get("partner_id") or 0) or None,
        "partner_name": str(target.get("partner_name") or ""),
        "analytic_account_id": int(target.get("analytic_account_id") or 0) or None,
        "analytic_account_name": str(target.get("analytic_account_name") or ""),
        "tax_id": tax_id,
        "tax_name": str(target.get("tax_name") or ""),
        "tax_rate": target.get("tax_rate"),
        "tax_amount_type": str(target.get("tax_amount_type") or ""),
        "tax_type_use": str(target.get("tax_type_use") or ""),
        "tax_price_include": bool(target.get("tax_price_include")),
        "tax_account_id": int(target.get("tax_account_id") or 0) or None,
        "tax_account_code": str(target.get("tax_account_code") or ""),
        "tax_account_name": str(target.get("tax_account_name") or ""),
        "tax_amount_mode": tax_amount_mode if tax_id else None,
    }
