"""Capabilities module — runtime contract of what is enabled in this frame.

This package is the **single source of truth** for "which surface area
of the application is currently live". It exposes:

- :class:`app.capabilities.service.CapabilitiesService` — read-only
  service that turns a ``DeploymentFrame`` into a deterministic
  capability map.
- :class:`app.capabilities.router.router` — FastAPI router that serves
  the capability map at ``GET /api/v1/system/capabilities``.

The service is intentionally pure (no DB access, no I/O) so it can be
unit-tested without a database. Frontend code consumes the JSON payload
through the ``useCapabilities`` React hook and never reads
``DEPLOYMENT_FRAME`` directly.
"""
from app.capabilities.service import (
    CAPABILITY_NAMES,
    CapabilitiesService,
    CapabilitiesView,
)

__all__ = [
    "CAPABILITY_NAMES",
    "CapabilitiesService",
    "CapabilitiesView",
]