"""Small, capability-based contracts for ERP integrations.

Application code must depend on these protocols rather than importing a concrete
ERP SDK/provider.  Splitting capabilities keeps consumers from depending on
operations they do not use and lets providers be replaced independently.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ERPConnectionProvider(Protocol):
    provider_name: str
    url: str
    db: str

    def test_connection(self) -> dict[str, Any]: ...

    def get_company_info(self) -> dict[str, Any]: ...


@runtime_checkable
class ERPDiscoveryProvider(Protocol):
    provider_name: str
    url: str
    db: str

    def get_company_info(self) -> dict[str, Any]: ...

    def discover_accounts(self) -> list[dict[str, Any]]: ...

    def discover_journals(self) -> list[dict[str, Any]]: ...

    def discover_taxes(self) -> list[dict[str, Any]]: ...

    def discover_partners(self) -> list[dict[str, Any]]: ...

    def discover_analytic_accounts(self) -> list[dict[str, Any]]: ...

    def discover_products(self) -> list[dict[str, Any]]: ...

    def discover_employees(self) -> list[dict[str, Any]]: ...


@runtime_checkable
class ERPCommandProvider(Protocol):
    """Lowest-level escape hatch for provider-specific application gateways."""

    provider_name: str

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
    ) -> Any: ...


# Backwards-compatible alias for consumers that only need connection metadata.
ERPProvider = ERPConnectionProvider
