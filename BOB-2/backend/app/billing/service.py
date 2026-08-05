"""Billing service facade — the only type application code depends on.

The facade resolves the active provider from
``app.state.billing_provider`` at request time, falling back to a fresh
:class:`InMemoryBillingProvider` if no real provider is wired up.

Application code must call the facade, never a concrete provider:

    from app.billing import BillingService
    plans = BillingService(request.app).list_plans()

This indirection is what keeps the codebase SOLID: the rest of the
application depends on the protocol abstraction, not on any specific
provider implementation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.billing.in_memory_provider import InMemoryBillingProvider
from app.billing.types import (
    BillingProvider,
    PlanDefinition,
    PortalSession,
    WebhookEvent,
)

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


class BillingService:
    """Façade over the configured billing provider.

    Construct with the running :class:`FastAPI` application so the
    service can read ``app.state.billing_provider``. If the
    application state has not been initialized (unit tests), a fresh
    :class:`InMemoryBillingProvider` is used.
    """

    def __init__(self, app: "FastAPI | None" = None) -> None:
        self._app = app
        self._fallback = InMemoryBillingProvider()

    @property
    def provider(self) -> BillingProvider:
        """Return the active provider, or the in-memory fallback."""
        if self._app is None:
            return self._fallback
        configured = getattr(self._app.state, "billing_provider", None)
        if configured is None:
            return self._fallback
        return configured

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def list_plans(self) -> tuple[PlanDefinition, ...]:
        return self.provider.list_plans()

    def create_checkout_session(
        self,
        *,
        plan_id: str,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        tenant_id: str | None = None,
    ) -> dict:
        return self.provider.create_checkout_session(
            plan_id=plan_id,
            customer_email=customer_email,
            success_url=success_url,
            cancel_url=cancel_url,
            tenant_id=tenant_id,
        )

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> PortalSession:
        return self.provider.create_portal_session(
            customer_id=customer_id,
            return_url=return_url,
        )

    def verify_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str,
    ) -> WebhookEvent:
        return self.provider.verify_webhook(
            payload=payload,
            signature_header=signature_header,
        )


__all__ = ["BillingService"]