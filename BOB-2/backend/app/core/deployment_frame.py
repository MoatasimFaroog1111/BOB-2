"""Deployment frame selector.

A single source of truth for which surface area of GuardianAI is active in
the current deployment. The same codebase is configured as one of three
go-to-market frames without forking:

- ``enterprise``: single-tenant invitation-only asset sale (default).
- ``self_serve_saas``: multi-tenant subscription SaaS.
- ``hybrid_marketplace``: marketplace self-serve + operator-led onboarding.

The ``DeploymentFrame`` enum is exported and consumed by:

- ``app.capabilities.service.CapabilitiesService`` (the runtime contract
  the frontend reads via ``GET /api/v1/system/capabilities``).
- ``app.services.deployment_frame_check`` (fail-closed startup rules).
- Tests (parametrized matrix runs across all three frames).

This module deliberately does **not** import from ``app.core.config`` to
avoid a circular import (config imports from many places). The
``coerce`` function accepts either a ``Settings`` instance or a raw string
so callers can choose the entry point that suits them.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:  # pragma: no cover - import-only typing aid
    from app.core.config import Settings


class DeploymentFrame(str, Enum):
    """The GTM frame this deployment is configured to expose."""

    ENTERPRISE = "enterprise"
    SELF_SERVE_SAAS = "self_serve_saas"
    HYBRID_MARKETPLACE = "hybrid_marketplace"

    @classmethod
    def coerce(cls, value: Union[str, "DeploymentFrame", "Settings"]) -> "DeploymentFrame":
        """Resolve a frame from a string, an enum, or a ``Settings`` instance.

        A bare string that does not match any enum member raises
        ``ValueError``. ``Settings`` is resolved via its
        ``DEPLOYMENT_FRAME`` attribute. Passing an already-resolved
        ``DeploymentFrame`` is a no-op and returns it unchanged.
        """
        if isinstance(value, cls):
            return value
        if hasattr(value, "DEPLOYMENT_FRAME"):
            # Looks like a Settings-like object.
            value = getattr(value, "DEPLOYMENT_FRAME", "")
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in cls:
                if member.value == normalized:
                    return member
            valid = ", ".join(m.value for m in cls)
            raise ValueError(
                f"Unknown DEPLOYMENT_FRAME {value!r}. Valid values: {valid}"
            )
        raise TypeError(
            f"Cannot coerce deployment frame from {type(value).__name__}"
        )


__all__ = ["DeploymentFrame"]