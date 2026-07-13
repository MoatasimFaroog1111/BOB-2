"""Deprecated standalone entrypoint.

The GuardianAI UI now uses the authenticated, RBAC-protected API in BOB-2/backend.
Keeping a second unauthenticated financial backend would create a security bypass, so
this process intentionally exposes no document or journal data.
"""

from fastapi import FastAPI, HTTPException, status

app = FastAPI(
    title="GuardianAI Accountant (retired standalone API)",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health")
def health():
    return {"status": "retired", "replacement": "/api/v1"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def retired_endpoint(path: str):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "The standalone GuardianAI API has been retired. "
            "Use the authenticated BOB-2 backend under /api/v1."
        ),
    )
