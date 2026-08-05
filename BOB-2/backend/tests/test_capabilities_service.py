"""Tests for :class:`app.capabilities.service.CapabilitiesService`.

The service is intentionally pure (no DB, no I/O). Every test here
just exercises the deterministic capability map for each frame.
"""
from __future__ import annotations

import pytest

from app.capabilities.service import (
    CAPABILITY_INVITE_ONLY_SIGNUP,
    CAPABILITY_MARKETING_SITE,
    CAPABILITY_NAMES,
    CAPABILITY_OPERATOR_ONBOARDING,
    CAPABILITY_SELF_SERVE_SIGNUP,
    CAPABILITY_STRIPE_BILLING,
    CapabilitiesService,
)
from app.core.deployment_frame import DeploymentFrame


@pytest.mark.parametrize("frame", list(DeploymentFrame))
def test_every_frame_lists_every_capability(frame: DeploymentFrame) -> None:
    """Every capability key must appear in every frame's map."""
    view = CapabilitiesService(frame).view()
    for name in CAPABILITY_NAMES:
        assert name in view.capabilities, f"{frame.value} missing {name}"
        assert view.capabilities[name] in {"default", "optional", "disabled"}


def test_enterprise_frame_disables_self_serve_and_billing() -> None:
    caps = CapabilitiesService(DeploymentFrame.ENTERPRISE).view().capabilities
    assert caps[CAPABILITY_SELF_SERVE_SIGNUP] == "disabled"
    assert caps[CAPABILITY_STRIPE_BILLING] == "disabled"
    assert caps[CAPABILITY_MARKETING_SITE] == "disabled"
    assert caps[CAPABILITY_INVITE_ONLY_SIGNUP] == "default"


def test_self_serve_saas_frame_enables_self_serve_and_billing() -> None:
    caps = CapabilitiesService(DeploymentFrame.SELF_SERVE_SAAS).view().capabilities
    assert caps[CAPABILITY_SELF_SERVE_SIGNUP] == "default"
    assert caps[CAPABILITY_STRIPE_BILLING] == "default"
    assert caps[CAPABILITY_MARKETING_SITE] == "default"
    assert caps[CAPABILITY_INVITE_ONLY_SIGNUP] == "disabled"


def test_hybrid_marketplace_frame_enables_everything() -> None:
    caps = CapabilitiesService(DeploymentFrame.HYBRID_MARKETPLACE).view().capabilities
    assert caps[CAPABILITY_SELF_SERVE_SIGNUP] == "default"
    assert caps[CAPABILITY_STRIPE_BILLING] == "default"
    assert caps[CAPABILITY_MARKETING_SITE] == "default"
    assert caps[CAPABILITY_OPERATOR_ONBOARDING] == "default"


def test_view_is_immutable() -> None:
    """Capabilities view is frozen dataclass; mutation of the view itself must raise."""
    from dataclasses import FrozenInstanceError

    view = CapabilitiesService(DeploymentFrame.ENTERPRISE).view()
    with pytest.raises(FrozenInstanceError):
        view.frame = "mutated"  # type: ignore[misc]


def test_view_dict_has_frame_and_capabilities() -> None:
    view = CapabilitiesService(DeploymentFrame.ENTERPRISE).view()
    d = view.as_dict()
    assert d["frame"] == "enterprise"
    assert d["capabilities"][CAPABILITY_INVITE_ONLY_SIGNUP] == "default"


def test_coerce_string_and_settings() -> None:
    """DeploymentFrame.coerce accepts strings and Settings-like objects."""
    from types import SimpleNamespace

    assert DeploymentFrame.coerce("hybrid_marketplace") is DeploymentFrame.HYBRID_MARKETPLACE
    assert DeploymentFrame.coerce(DeploymentFrame.SELF_SERVE_SAAS) is DeploymentFrame.SELF_SERVE_SAAS
    settings_like = SimpleNamespace(DEPLOYMENT_FRAME="enterprise")
    # cast via string because the Protocol type uses a Protocol; we still
    # want runtime acceptance of Settings-like objects.
    assert DeploymentFrame.coerce(settings_like) is DeploymentFrame.ENTERPRISE  # type: ignore[arg-type]


def test_coerce_rejects_unknown_string() -> None:
    with pytest.raises(ValueError, match="Unknown DEPLOYMENT_FRAME"):
        DeploymentFrame.coerce("not-a-real-frame")


def test_coerce_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        DeploymentFrame.coerce(123)  # type: ignore[arg-type]