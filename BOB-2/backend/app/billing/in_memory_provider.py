"""In-memory billing provider — deterministic, always-available fallback.

This provider is wired up by default in every deployment frame. It:

- Returns a fixed plan catalog derived from :data:`DEFAULT_PLANS`.
- Returns an error for ``create_checkout_session`` /
  ``create_portal_session`` — the in-memory ledger cannot host a real
  checkout flow.
- Records webhook events in :data:`WEBHOOK_LOG` so tests can assert
  they were delivered.
- Implements a trivial HMAC-style signature verification so the
  webhook entrypoint can exercise the full path during smoke tests.

This implementation deliberately never touches the database. A future
``LedgerBillingProvider`` may swap in to persist invoice rows, but that
work belongs to P3.x — not to P3.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
from typing import Dict, List

from app.billing.types import (
    BillingProviderError,
    BillingProviderNotConfiguredError,
    PlanDefinition,
    PlanInterval,
    PortalSession,
    WebhookEvent,
)


DEFAULT_PLANS: tuple[PlanDefinition, ...] = (
    PlanDefinition(
        id="starter",
        name="Starter",
        interval=PlanInterval.MONTHLY,
        amount_cents=9_900,  # $99.00
        currency="USD",
        description="Single-tenant starter plan for boutique firms.",
        trial_days=14,
        features=(
            "Up to 250 documents / month",
            "1 Odoo organization",
            "Email support",
        ),
    ),
    PlanDefinition(
        id="professional",
        name="Professional",
        interval=PlanInterval.MONTHLY,
        amount_cents=49_900,  # $499.00
        currency="USD",
        description="Mid-market firms and audit teams.",
        trial_days=14,
        features=(
            "Up to 5,000 documents / month",
            "3 Odoo organizations",
            "Priority email + chat support",
            "Audit chain export",
        ),
    ),
    PlanDefinition(
        id="enterprise",
        name="Enterprise",
        interval=PlanInterval.YEARLY,
        amount_cents=240_000_00,  # $24,000/year (proxy for $2K-$10K/mo negotiated)
        currency="USD",
        description="Custom pricing. Operator-led onboarding and SSO.",
        trial_days=0,
        features=(
            "Unlimited documents",
            "Unlimited Odoo organizations",
            "SAML / OIDC SSO",
            "Dedicated CSM",
        ),
    ),
    PlanDefinition(
        id="lifetime_marketplace",
        name="Marketplace Lifetime",
        interval=PlanInterval.LIFETIME,
        amount_cents=79_900,  # $799 one-time
        currency="USD",
        description="Lifetime access via marketplace channels (AppSumo etc.).",
        trial_days=0,
        features=(
            "Single-tenant lifetime access",
            "Operator-led first-value session",
            "12 months of email support",
        ),
    ),
)


class InMemoryBillingProvider:
    """Deterministic billing ledger for development and tests."""

    name = "in_memory"

    def __init__(
        self,
        *,
        plans: tuple[PlanDefinition, ...] = DEFAULT_PLANS,
        signing_secret: str = "in-memory-dev-signing-secret",
    ) -> None:
        self._plans = plans
        self._signing_secret = signing_secret.encode("utf-8")
        self._lock = threading.Lock()
        self._webhook_log: List[WebhookEvent] = []

    def list_plans(self) -> tuple[PlanDefinition, ...]:
        return self._plans

    def create_checkout_session(
        self,
        *,
        plan_id: str,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        tenant_id: str | None = None,
    ) -> Dict[str, str]:
        raise BillingProviderNotConfiguredError(
            "In-memory billing provider cannot host a checkout. "
            "Configure STRIPE_SECRET_KEY or LEMONSQUEEZY_API_KEY to enable hosted checkout."
        )

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> PortalSession:
        raise BillingProviderNotConfiguredError(
            "In-memory billing provider cannot host a billing portal. "
            "Configure a real billing provider to enable customer-self-service."
        )

    def sign_payload(self, payload: bytes) -> str:
        """Return the HMAC-SHA256 hex digest for a webhook body.

        Exposed so tests can construct valid signatures without
        importing the ``hmac`` module directly.
        """
        return hmac.new(self._signing_secret, payload, hashlib.sha256).hexdigest()

    def verify_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str,
    ) -> WebhookEvent:
        """Verify a webhook signature and record the event in the log.

        The in-memory provider expects a bare hex digest in
        ``signature_header``. Real providers will have their own
        envelope formats; those providers parse and verify
        independently.
        """
        expected = self.sign_payload(payload)
        if not hmac.compare_digest(expected, signature_header.strip()):
            raise BillingProviderError("Invalid webhook signature for in-memory provider")
        # The in-memory provider treats the payload as opaque JSON text.
        # Real providers parse it; this one just records it.
        event = WebhookEvent(
            type="in_memory.test",
            customer_id=None,
            invoice_id=None,
            subscription_id=None,
            payload={"raw_size": len(payload)},
            signature=signature_header,
        )
        with self._lock:
            self._webhook_log.append(event)
        return event

    @property
    def webhook_log(self) -> tuple[WebhookEvent, ...]:
        """Snapshot of the webhook events recorded so far."""
        with self._lock:
            return tuple(self._webhook_log)


__all__ = ["InMemoryBillingProvider", "DEFAULT_PLANS"]