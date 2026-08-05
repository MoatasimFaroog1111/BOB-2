"""Tests for the in-memory billing provider and the BillingService facade."""
from __future__ import annotations

import pytest

from app.billing import BillingService
from app.billing.in_memory_provider import (
    DEFAULT_PLANS,
    InMemoryBillingProvider,
)
from app.billing.types import (
    BillingProviderNotConfiguredError,
    PlanInterval,
)


def test_default_plans_have_three_real_plans_plus_marketplace() -> None:
    """The default catalog covers the three core plans + the marketplace tier."""
    ids = {p.id for p in DEFAULT_PLANS}
    assert ids == {"starter", "professional", "enterprise", "lifetime_marketplace"}


def test_default_plans_use_real_currency_codes() -> None:
    for plan in DEFAULT_PLANS:
        assert len(plan.currency) == 3
        assert plan.currency.isalpha()


def test_default_plans_have_valid_intervals() -> None:
    for plan in DEFAULT_PLANS:
        assert plan.interval in set(PlanInterval)


def test_plan_definition_rejects_negative_amount() -> None:
    from app.billing.types import PlanDefinition

    with pytest.raises(ValueError):
        PlanDefinition(
            id="bad",
            name="Bad",
            interval=PlanInterval.MONTHLY,
            amount_cents=-1,
            currency="USD",
        )


def test_plan_definition_rejects_bad_currency() -> None:
    from app.billing.types import PlanDefinition

    with pytest.raises(ValueError):
        PlanDefinition(
            id="bad",
            name="Bad",
            interval=PlanInterval.MONTHLY,
            amount_cents=100,
            currency="US",
        )


def test_in_memory_provider_lists_default_plans() -> None:
    provider = InMemoryBillingProvider()
    assert provider.name == "in_memory"
    assert provider.list_plans() == DEFAULT_PLANS


def test_in_memory_provider_rejects_checkout() -> None:
    provider = InMemoryBillingProvider()
    with pytest.raises(BillingProviderNotConfiguredError):
        provider.create_checkout_session(
            plan_id="starter",
            customer_email="buyer@example.com",
            success_url="https://app/ok",
            cancel_url="https://app/cancel",
        )


def test_in_memory_provider_rejects_portal() -> None:
    provider = InMemoryBillingProvider()
    with pytest.raises(BillingProviderNotConfiguredError):
        provider.create_portal_session(
            customer_id="cust-1", return_url="https://app/back"
        )


def test_in_memory_provider_signs_and_verifies_webhook() -> None:
    provider = InMemoryBillingProvider()
    payload = b'{"type":"invoice.paid","customer":"cust-1"}'
    sig = provider.sign_payload(payload)
    event = provider.verify_webhook(payload=payload, signature_header=sig)
    assert event.type == "in_memory.test"
    assert len(provider.webhook_log) == 1


def test_in_memory_provider_rejects_tampered_signature() -> None:
    from app.billing.types import BillingProviderError

    provider = InMemoryBillingProvider()
    payload = b'{"type":"invoice.paid"}'
    with pytest.raises(BillingProviderError):
        provider.verify_webhook(payload=payload, signature_header="deadbeef" * 8)


def test_billing_service_uses_fallback_when_app_is_none() -> None:
    """Constructed without an app, the facade returns the in-memory provider."""
    service = BillingService(app=None)
    assert service.provider_name == "in_memory"
    assert service.list_plans() == DEFAULT_PLANS


def test_billing_service_resolves_provider_from_app_state() -> None:
    """When ``app.state.billing_provider`` is set, the facade returns it."""
    from types import SimpleNamespace

    custom_provider = InMemoryBillingProvider(signing_secret="custom-secret")
    app = SimpleNamespace(state=SimpleNamespace(billing_provider=custom_provider))
    service = BillingService(app=app)  # type: ignore[arg-type]
    assert service.provider_name == "in_memory"
    # Verify the facade actually delegates to the custom provider by
    # checking its signature secret is what we configured. The provider
    # is the concrete InMemoryBillingProvider (not the protocol), so
    # the extra method is accessible.
    payload = b"hello"
    sig = service.provider.sign_payload(payload)  # type: ignore[attr-defined]
    assert sig == custom_provider.sign_payload(payload)