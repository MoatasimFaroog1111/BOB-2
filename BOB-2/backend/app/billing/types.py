"""Billing types — the protocol every billing provider implements.

The protocol is intentionally narrow (Liskov-friendly): any class that
implements these methods is a valid billing provider. Application code
never imports a concrete provider class directly; it depends only on
the protocol via :class:`app.billing.service.BillingService`.

Dataclasses are frozen so the protocol contract is immutable across
the wire. Datetimes use ``datetime`` (timezone-aware UTC) — never
``time.time()`` floats — so the in-memory ledger matches what an
external provider would return.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Protocol, runtime_checkable


class PlanInterval(str, Enum):
    """Cadence at which a subscription bills the customer."""

    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


@dataclass(frozen=True)
class PlanDefinition:
    """Catalog entry for a single billing plan.

    The id is provider-agnostic (the facade maps it to whatever the
    real provider calls it). ``trial_days`` defaults to 0; a non-zero
    value creates a Stripe-style trial on checkout.
    """

    id: str
    name: str
    interval: PlanInterval
    amount_cents: int
    currency: str
    description: str = ""
    trial_days: int = 0
    features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.amount_cents < 0:
            raise ValueError("amount_cents must be non-negative")
        if self.trial_days < 0:
            raise ValueError("trial_days must be non-negative")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a 3-letter ISO code")


@dataclass(frozen=True)
class Invoice:
    """A single invoice issued by the provider."""

    id: str
    customer_id: str
    amount_cents: int
    currency: str
    status: str  # "draft" | "open" | "paid" | "void" | "uncollectible"
    hosted_url: Optional[str] = None
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PortalSession:
    """A short-lived URL that lets the customer manage their billing."""

    url: str
    expires_at: datetime


@dataclass(frozen=True)
class WebhookEvent:
    """A normalized webhook delivery from any provider.

    ``raw`` preserves the original payload for debugging; ``signature``
    is the provider-specific signature header value (Stripe sends
    ``t=...,v1=...``, Lemon Squeezy sends an HMAC hex digest).
    """

    type: str
    customer_id: Optional[str]
    invoice_id: Optional[str]
    subscription_id: Optional[str]
    payload: Mapping[str, Any]
    signature: str
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BillingProviderError(RuntimeError):
    """Base class for provider-side failures."""


class BillingProviderNotConfiguredError(BillingProviderError):
    """Raised when a provider-specific method is called without config.

    For example, ``create_checkout_session`` on the in-memory provider
    raises this so the API surfaces a 501 Not Implemented rather than
    silently recording fake data.
    """


@runtime_checkable
class BillingProvider(Protocol):
    """The single contract every billing provider must implement.

    The protocol is runtime-checkable so the test suite can verify
    that a custom provider matches the expected shape without a static
    type checker.
    """

    @property
    def name(self) -> str:
        """Stable identifier for this provider (``"in_memory"``, ``"stripe"``...)."""
        ...

    def list_plans(self) -> tuple[PlanDefinition, ...]:
        """Return the canonical plan catalog for this provider."""
        ...

    def create_checkout_session(
        self,
        *,
        plan_id: str,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Begin a hosted checkout. Returns ``{"id": ..., "url": ...}``."""
        ...

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> PortalSession:
        """Open the customer-self-service portal."""
        ...

    def verify_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str,
    ) -> WebhookEvent:
        """Verify and normalize a webhook delivery.

        Raises :class:`BillingProviderError` if the signature is
        invalid or the payload cannot be parsed.
        """
        ...


__all__ = [
    "BillingProvider",
    "BillingProviderError",
    "BillingProviderNotConfiguredError",
    "Invoice",
    "PlanDefinition",
    "PlanInterval",
    "PortalSession",
    "WebhookEvent",
]