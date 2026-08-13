from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.tenant_erp_service import OdooReferenceValidator


class FakeTaxERP:
    def __init__(self, *, company_id: int = 7, complex_tax: bool = False):
        self.company_id = company_id
        self.complex_tax = complex_tax

    def execute_kw(self, model, method, args, kwargs):
        assert method == "search_read"
        if model == "account.tax":
            return [{
                "id": 15,
                "name": "VAT 15% Purchases",
                "active": True,
                "amount": 15.0,
                "amount_type": "percent",
                "type_tax_use": "purchase",
                "price_include": False,
                "company_id": [self.company_id, "Guardian"],
                "invoice_repartition_line_ids": [150, 151, 152] if self.complex_tax else [150, 151],
            }]
        if model == "account.tax.repartition.line":
            rows = [
                {"id": 150, "repartition_type": "base", "factor_percent": 100.0, "account_id": False},
                {"id": 151, "repartition_type": "tax", "factor_percent": 100.0, "account_id": [300, "VAT Input"]},
            ]
            if self.complex_tax:
                rows.append({"id": 152, "repartition_type": "tax", "factor_percent": 100.0, "account_id": [301, "Second VAT"]})
            return rows
        if model == "account.account":
            return [{"id": 300, "code": "102020", "name": "VAT Input"}]
        raise AssertionError(model)


def test_resolves_simple_percentage_tax_to_odoo_posting_account():
    tax = OdooReferenceValidator().tax(FakeTaxERP(), 15, company_id=7)
    assert tax["amount"] == 15.0
    assert tax["type_tax_use"] == "purchase"
    assert tax["tax_account_id"] == 300
    assert tax["tax_account_code"] == "102020"


def test_rejects_tax_from_another_company():
    with pytest.raises(HTTPException) as exc_info:
        OdooReferenceValidator().tax(FakeTaxERP(company_id=8), 15, company_id=7)
    assert exc_info.value.status_code == 422


def test_rejects_complex_multi_account_tax_repartition():
    with pytest.raises(HTTPException) as exc_info:
        OdooReferenceValidator().tax(FakeTaxERP(complex_tax=True), 15, company_id=7)
    assert exc_info.value.status_code == 422
