"""Regression guards against legacy diagnostic and secret-bearing routes."""

from app.api.v1.erp import router


def test_legacy_debug_and_telegram_secret_routes_are_not_registered():
    paths = {route.path for route in router.routes}

    assert "/debug-parse-status" not in paths
    assert "/telegram-config" not in paths


def test_legacy_bank_reconciliation_routes_are_owned_by_hardened_router_only():
    paths = {route.path for route in router.routes}

    assert "/bank-reconciliation" not in paths
    assert "/bank-statement-parse" not in paths
