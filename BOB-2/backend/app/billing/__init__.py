"""Billing module — provider-agnostic subscription/billing surface.

The module exposes a single, narrow interface
(:class:`app.billing.types.BillingProvider`) and a deterministic
in-process implementation
(:class:`app.billing.in_memory_provider.InMemoryBillingProvider`) that
is always available, even when no external billing account (Stripe,
Lemon Squeezy, Paddle, ...) is configured.

The facade (:class:`app.billing.service.BillingService`) is the only
type application code should depend on. The facade resolves the active
provider from ``app.state.billing_provider`` at request time, falling
back to the in-memory provider if no real provider is wired up. This
keeps the codebase fully runnable for any deployment frame in a local
environment with only PostgreSQL and Redis.
"""
from app.billing.service import BillingService
from app.billing.types import (
    BillingProvider,
    BillingProviderError,
    BillingProviderNotConfiguredError,
    Invoice,
    PlanDefinition,
    PlanInterval,
    PortalSession,
    WebhookEvent,
)

__all__ = [
    "BillingService",
    "BillingProvider",
    "BillingProviderError",
    "BillingProviderNotConfiguredError",
    "Invoice",
    "PlanDefinition",
    "PlanInterval",
    "PortalSession",
    "WebhookEvent",
]