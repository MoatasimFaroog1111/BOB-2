"""Pure capability service for the multi-GTM frame switch.

This module is intentionally side-effect-free: it reads a
``DeploymentFrame`` and returns a frozen :class:`CapabilitiesView`.
There is no database access and no I/O, which means the service can be
unit-tested with a plain ``DeploymentFrame`` argument and nothing else.

Each capability is one of three tri-state values:

- ``"default"``     — the capability is on by default in this frame.
- ``"optional"``    — the capability exists but is configured off.
- ``"disabled"``    — the capability is not available in this frame.

The frontend converts those three values into:

- ``"default"``     → render the UI / accept the API calls.
- ``"optional"``    → hide unless the tenant explicitly opts in.
- ``"disabled"``    → return 404 / hide entirely.

The capability names are exported in :data:`CAPABILITY_NAMES` so the
frontend can iterate deterministically without hard-coding strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Mapping

from app.core.deployment_frame import DeploymentFrame

# Stable string identifiers. Tests reference these so a rename becomes
# a deliberate change.
CAPABILITY_INVITE_ONLY_SIGNUP = "invite_only_signup"
CAPABILITY_SELF_SERVE_SIGNUP = "self_serve_signup"
CAPABILITY_STRIPE_BILLING = "stripe_billing"
CAPABILITY_MARKETPLACE_BILLING = "marketplace_billing"
CAPABILITY_MARKETING_SITE = "marketing_site"
CAPABILITY_OPERATOR_ONBOARDING = "operator_onboarding"
CAPABILITY_PUBLIC_DEMO = "public_demo"
CAPABILITY_TENANT_METERING = "tenant_metering"
CAPABILITY_AUDIT_CHAIN_S3_EXPORT = "audit_chain_s3_export"

# The full ordered list of capability keys — exported so callers can
# iterate without re-declaring the set.
CAPABILITY_NAMES: tuple[str, ...] = (
    CAPABILITY_INVITE_ONLY_SIGNUP,
    CAPABILITY_SELF_SERVE_SIGNUP,
    CAPABILITY_STRIPE_BILLING,
    CAPABILITY_MARKETPLACE_BILLING,
    CAPABILITY_MARKETING_SITE,
    CAPABILITY_OPERATOR_ONBOARDING,
    CAPABILITY_PUBLIC_DEMO,
    CAPABILITY_TENANT_METERING,
    CAPABILITY_AUDIT_CHAIN_S3_EXPORT,
)


# Default capability maps per frame. Each tuple is a complete mapping —
# every capability must appear, never partially.
_FRAME_CAPABILITIES: Mapping[DeploymentFrame, Dict[str, str]] = {
    DeploymentFrame.ENTERPRISE: {
        CAPABILITY_INVITE_ONLY_SIGNUP: "default",
        CAPABILITY_SELF_SERVE_SIGNUP: "disabled",
        CAPABILITY_STRIPE_BILLING: "disabled",
        CAPABILITY_MARKETPLACE_BILLING: "disabled",
        CAPABILITY_MARKETING_SITE: "disabled",
        CAPABILITY_OPERATOR_ONBOARDING: "optional",
        CAPABILITY_PUBLIC_DEMO: "disabled",
        CAPABILITY_TENANT_METERING: "optional",
        CAPABILITY_AUDIT_CHAIN_S3_EXPORT: "optional",
    },
    DeploymentFrame.SELF_SERVE_SAAS: {
        CAPABILITY_INVITE_ONLY_SIGNUP: "disabled",
        CAPABILITY_SELF_SERVE_SIGNUP: "default",
        CAPABILITY_STRIPE_BILLING: "default",
        CAPABILITY_MARKETPLACE_BILLING: "optional",
        CAPABILITY_MARKETING_SITE: "default",
        CAPABILITY_OPERATOR_ONBOARDING: "disabled",
        CAPABILITY_PUBLIC_DEMO: "optional",
        CAPABILITY_TENANT_METERING: "default",
        CAPABILITY_AUDIT_CHAIN_S3_EXPORT: "default",
    },
    DeploymentFrame.HYBRID_MARKETPLACE: {
        CAPABILITY_INVITE_ONLY_SIGNUP: "optional",
        CAPABILITY_SELF_SERVE_SIGNUP: "default",
        CAPABILITY_STRIPE_BILLING: "default",
        CAPABILITY_MARKETPLACE_BILLING: "default",
        CAPABILITY_MARKETING_SITE: "default",
        CAPABILITY_OPERATOR_ONBOARDING: "default",
        CAPABILITY_PUBLIC_DEMO: "default",
        CAPABILITY_TENANT_METERING: "default",
        CAPABILITY_AUDIT_CHAIN_S3_EXPORT: "default",
    },
}


@dataclass(frozen=True)
class CapabilitiesView:
    """The capability map for the current frame, with frame identity.

    ``frame`` is repeated in the payload so the frontend does not have to
    make a separate call to discover which frame is active. ``build``
    and ``git_sha`` are populated by the router (which has access to
    the running build) and may be empty strings in unit tests.
    """

    frame: str
    capabilities: Dict[str, str] = field(default_factory=dict)
    build: str = ""
    git_sha: str = ""

    def as_dict(self) -> dict:
        """Return a JSON-serializable view of the capabilities."""
        d = asdict(self)
        # ``asdict`` returns ``Dict[str, str]`` for capabilities already;
        # we explicitly cast for type-checkers.
        d["capabilities"] = dict(self.capabilities)
        return d


class CapabilitiesService:
    """Pure capability resolver.

    Construct with a ``DeploymentFrame``; call :meth:`view` to obtain a
    frozen :class:`CapabilitiesView`. The service holds no state across
    calls.
    """

    def __init__(self, frame: DeploymentFrame) -> None:
        self._frame = frame

    @property
    def frame(self) -> DeploymentFrame:
        return self._frame

    def view(self, *, build: str = "", git_sha: str = "") -> CapabilitiesView:
        """Resolve the capability map for the configured frame."""
        caps = _FRAME_CAPABILITIES[self._frame]
        # Defensive copy so callers can't mutate the canonical map.
        return CapabilitiesView(
            frame=self._frame.value,
            capabilities=dict(caps),
            build=build,
            git_sha=git_sha,
        )


__all__ = [
    "CapabilitiesService",
    "CapabilitiesView",
    "CAPABILITY_NAMES",
] + [
    name
    for name in (
        CAPABILITY_INVITE_ONLY_SIGNUP,
        CAPABILITY_SELF_SERVE_SIGNUP,
        CAPABILITY_STRIPE_BILLING,
        CAPABILITY_MARKETPLACE_BILLING,
        CAPABILITY_MARKETING_SITE,
        CAPABILITY_OPERATOR_ONBOARDING,
        CAPABILITY_PUBLIC_DEMO,
        CAPABILITY_TENANT_METERING,
        CAPABILITY_AUDIT_CHAIN_S3_EXPORT,
    )
]