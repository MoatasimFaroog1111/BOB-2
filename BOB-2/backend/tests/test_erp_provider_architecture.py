from __future__ import annotations

from typing import Any

import pytest

from app.erp.base import ERPConnectionProvider, ERPDiscoveryProvider
from app.erp.discovery import run_discovery_orchestrator
from app.erp.factory import ERPProviderRegistry


class FakeProvider:
    provider_name = "fake"

    def __init__(self, url: str, db: str, username: str, password: str) -> None:
        self.url = url
        self.db = db

    def test_connection(self) -> dict[str, Any]:
        return {"connected": True}

    def get_company_info(self) -> dict[str, Any]:
        return {"companies": []}

    def discover_accounts(self): return []
    def discover_journals(self): return []
    def discover_taxes(self): return []
    def discover_partners(self): return []
    def discover_analytic_accounts(self): return []
    def discover_products(self): return []
    def discover_employees(self): return []


class ConnectionOnlyProvider:
    """A provider that only implements ERPConnectionProvider, not discovery.

    Mirrors real providers like the cloud-accounting adapters (SAP, Oracle,
    Business Central, QuickBooks, Xero) that only support test_connection /
    get_company_info today.
    """

    provider_name = "connection-only"
    url = "https://erp.example"
    db = "db"

    def test_connection(self) -> dict[str, Any]:
        return {"connected": True}

    def get_company_info(self) -> dict[str, Any]:
        return {"companies": []}


def test_registry_is_open_for_extension_without_factory_changes() -> None:
    registry = ERPProviderRegistry()
    registry.register("fake", FakeProvider)

    provider = registry.create(
        "fake", url="https://erp.example", db="db", username="u", password="p"
    )

    assert isinstance(provider, ERPConnectionProvider)
    assert isinstance(provider, ERPDiscoveryProvider)


def test_registry_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported ERP provider"):
        ERPProviderRegistry().create(
            "unknown", url="https://erp.example", db="db", username="u", password="p"
        )


def test_discovery_orchestrator_rejects_connection_only_provider() -> None:
    """Substituting a connection-only provider must fail with a clear error,
    not an AttributeError, preserving the discovery Protocol's contract (LSP)."""
    with pytest.raises(ValueError, match="does not support structure discovery"):
        run_discovery_orchestrator(ConnectionOnlyProvider())
