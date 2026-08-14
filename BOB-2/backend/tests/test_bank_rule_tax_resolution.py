from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.tenant_erp_service import OdooReferenceValidator


class FakeTaxERP:
    def __init__(
        self,
        *,
        company_id: int = 7,
        complex_tax: bool = False,
        refund_account_id: int = 300,
    ):
        self.company_id = company_id
        self.complex_tax = complex_tax
        self.refund_account_id = refund_account_id

    @staticmethod
    def _domain_record_id(args):
        try:
            domain = args[0]
            for condition in domain:
                if condition[0] == "id" and condition[1] == "=":
                    return int(condition[2])
        except (TypeError, ValueError, IndexError):
            return None
        return None

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
                "refund_repartition_line_ids": [160, 161],
            }]
        if model == "account.tax.repartition.line":
            requested_ids = set(args[0][0][2])
            rows = []
            if 150 in requested_ids:
                rows.extend([
                    {"id": 150, "repartition_type": "base", "factor_percent": 100.0, "account_id": False},
                    {"id": 151, "repartition_type": "tax", "factor_percent": 100.0, "account_id": [300, "VAT Input"]},
                ])
                if self.complex_tax:
                    rows.append({"id": 152, "repartition_type": "tax", "factor_percent": 100.0, "account_id": [301, "Second VAT"]})
            if 160 in requested_ids:
                rows.extend([
                    {"id": 160, "repartition_type": "base", "factor_percent": 100.0, "account_id": False},
                    {"id": 161, "repartition_type": "tax", "factor_percent": 100.0, "account_id": [self.refund_account_id, "VAT Refund"]},
                ])
            return rows
        if model == "account.account":
            record_id = self._domain_record_id(args)
            if record_id == 200:
                return [{"id": 200, "code": "400051", "name": "Other Bank Charges"}]
            if record_id == 301:
                return [{"id": 301, "code": "102021", "name": "VAT Refund"}]
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


def test_rejects_tax_when_invoice_and_refund_accounts_differ():
    with pytest.raises(HTTPException) as exc_info:
        OdooReferenceValidator().tax(FakeTaxERP(refund_account_id=301), 15, company_id=7)
    assert exc_info.value.status_code == 422
    assert "different invoice and refund" in str(exc_info.value.detail)


def test_target_snapshot_revalidates_tax_against_stored_company_when_caller_omits_company():
    target = {
        "account_id": 200,
        "tax_id": 15,
        "tax_company_id": 7,
    }
    with pytest.raises(HTTPException) as exc_info:
        OdooReferenceValidator().target_snapshot(FakeTaxERP(company_id=8), target)
    assert exc_info.value.status_code == 422
    assert "another company" in str(exc_info.value.detail)
