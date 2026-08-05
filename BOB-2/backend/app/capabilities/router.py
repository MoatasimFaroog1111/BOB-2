"""HTTP router for the capabilities endpoint.

Exposes:

- ``GET /api/v1/system/capabilities`` — public, unauthenticated, returns
  the capability map for the active frame.

The endpoint is intentionally unauthenticated so the marketing site and
signup page can read it before any user is logged in. It leaks no
secrets: only the boolean-like capability states and the frame name.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.capabilities.service import CapabilitiesService, CapabilitiesView
from app.core.deployment_frame import DeploymentFrame

router = APIRouter(tags=["capabilities"])


def _resolve_git_sha(repo_root: Path) -> str:
    """Best-effort lookup of the current git SHA. Empty on failure.

    Never raises — the capability endpoint must always respond.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_capabilities_service(request: Request) -> CapabilitiesService:
    """FastAPI dependency that builds a service from ``app.state.frame``.

    The ``frame`` is resolved once in the application lifespan and
    stored on ``request.app.state.frame`` so we never re-read
    ``DEPLOYMENT_FRAME`` from the environment on every request.
    """
    frame: DeploymentFrame = getattr(request.app.state, "frame")
    return CapabilitiesService(frame)


@router.get("/capabilities", response_model=None)
def get_capabilities(
    service: CapabilitiesService = Depends(get_capabilities_service),
) -> dict:
    """Return the capability map for the current deployment frame.

    Always 200 OK — the response body itself tells the caller what is
    available. The endpoint does not require auth and does not leak
    any secret material.
    """
    build = os.getenv("BUILD_TAG", "") or os.getenv("RAILWAY_GIT_COMMIT_SHA", "")
    git_sha = _resolve_git_sha(Path(__file__).resolve().parents[3])
    view: CapabilitiesView = service.view(build=build, git_sha=git_sha)
    return view.as_dict()


__all__ = ["router", "get_capabilities_service"]