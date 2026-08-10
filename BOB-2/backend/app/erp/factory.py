"""Extensible composition root for ERP providers."""

from __future__ import annotations

from collections.abc import Callable

from app.erp.base import ERPConnectionProvider
from app.erp.providers.odoo import OdooProvider

ERPProviderBuilder = Callable[..., ERPConnectionProvider]


class ERPProviderRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, ERPProviderBuilder] = {}

    @staticmethod
    def _key(provider: str) -> str:
        key = provider.lower().strip()
        if not key:
            raise ValueError("ERP provider name is required.")
        return key

    def register(self, provider: str, builder: ERPProviderBuilder) -> None:
        self._builders[self._key(provider)] = builder

    def create(self, provider: str, **credentials: str) -> ERPConnectionProvider:
        key = self._key(provider)
        builder = self._builders.get(key)
        if builder is None:
            raise ValueError(f"Unsupported ERP provider: {provider}")
        return builder(**credentials)


provider_registry = ERPProviderRegistry()
provider_registry.register("odoo", OdooProvider)


def get_erp_provider(
    provider: str,
    url: str,
    db: str,
    username: str,
    password: str,
) -> ERPConnectionProvider:
    """Compatibility facade; new composition code should inject a registry."""
    return provider_registry.create(
        provider,
        url=url,
        db=db,
        username=username,
        password=password,
    )
