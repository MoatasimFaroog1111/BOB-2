"""Tests for removal of the historical float-based ERP monetary routes."""

from decimal import Decimal

from fastapi.routing import APIRoute

from app.api.v1.erp_monetary_legacy import (
    LegacyProposeTransactionRequest,
    _build_proposal,
)
from app.api.v1.router import api_router
from app.core.money import parse_money


class ProposalERP:
    def execute_kw(self, model, method, args, kwargs=None):
        kwargs = kwargs or {}
        if model == "account.account" and method == "search_read":
            domain = args[0]
            account_type = next(
                (item[2] for item in domain if isinstance(item, (list, tuple)) and item[0] == "account_type"),
                None,
            )
            name_filter = next(
                (str(item[2]).lower() for item in domain if isinstance(item, (list, tuple)) and item[0] == "name"),
                None,
            )
            if account_type == "expense":
                return [{"id": 101, "code": "500001", "name": "Expense", "deprecated": False}]
            if account_type == "liability_payable":
                return [{"id": 202, "code": "200001", "name": "Payable", "deprecated": False}]
            if name_filter in {"suspense", "clearing"}:
                return [{"id": 303, "code": "100999", "name": "Suspense", "deprecated": False}]
            return [{"id": 101, "code": "500001", "name": "Expense", "deprecated": False}]
        if model == "res.partner" and method == "search_read":
            return [{"id": 44, "name": "Supplier LLC", "company_id": False}]
        if model == "account.journal" and method == "search_read":
            return [{"id": 9, "name": "Miscellaneous Operations", "type": "general"}]
        raise AssertionError(f"Unexpected ERP call: {model}.{method} {args} {kwargs}")


def test_application_registers_only_decimal_safe_legacy_monetary_endpoints():
    paths = {
        "/erp/propose-transaction": [],
        "/erp/register-document": [],
    }
    for route in api_router.routes:
        if isinstance(route, APIRoute) and route.path in paths:
            paths[route.path].append(route)

    for path, routes in paths.items():
        assert len(routes) == 1, (path, [route.endpoint.__module__ for route in routes])
        assert routes[0].endpoint.__module__ == "app.api.v1.erp_monetary_legacy"


def test_decimal_safe_proposal_returns_fixed_scale_balanced_strings():
    payload = LegacyProposeTransactionRequest(
        filename="invoice.pdf",
        document_class="invoice",
        amount="0.30",
        date="2026-07-15",
        partner_name="Supplier LLC",
    )
    proposal = _build_proposal(ProposalERP(), 1, payload)

    assert isinstance(payload.amount, Decimal)
    assert proposal["amount"] == "0.30"
    assert proposal["money_scale"] == 2
    assert proposal["lines"][0]["debit"] == "0.30"
    assert proposal["lines"][0]["credit"] == "0.00"
    assert proposal["lines"][1]["debit"] == "0.00"
    assert proposal["lines"][1]["credit"] == "0.30"
    assert parse_money(proposal["lines"][0]["debit"]) == parse_money(
        proposal["lines"][1]["credit"]
    )


def test_replacement_endpoints_require_authentication(client):
    propose = client.post(
        "/api/v1/erp/propose-transaction",
        json={
            "filename": "invoice.pdf",
            "document_class": "invoice",
            "amount": "100.00",
            "date": "2026-07-15",
        },
    )
    register = client.post(
        "/api/v1/erp/register-document",
        json={
            "filename": "invoice.pdf",
            "document_class": "invoice",
            "amount": "100.00",
            "date": "2026-07-15",
        },
    )
    assert propose.status_code == 401
    assert register.status_code == 401
