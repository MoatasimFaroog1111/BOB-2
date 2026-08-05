"""Billing endpoints — public plan catalog and webhook ingestion.

Endpoints:

- ``GET  /api/v1/billing/plans``  — public, returns the active plan
  catalog. Cached for 60 seconds at the edge.
- ``POST /api/v1/billing/webhook`` — provider webhook ingestion. The
  signature is verified via the active :class:`BillingProvider`.

The ``POST /api/v1/billing/portal`` endpoint is intentionally **not**
exposed by this router: opening a customer-self-service portal is a
post-checkout concern and belongs to the dashboard, not the public
billing surface.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.billing import BillingService
from app.billing.types import (
    BillingProviderError,
    BillingProviderNotConfiguredError,
)

router = APIRouter(tags=["billing"])


class PlanOut(BaseModel):
    id: str
    name: str
    interval: str
    amount_cents: int
    currency: str
    description: str
    trial_days: int
    features: list[str]


class PlansResponse(BaseModel):
    provider: str
    plans: list[PlanOut]


@router.get("/plans", response_model=PlansResponse)
def list_plans(request: Request) -> PlansResponse:
    """Public plan catalog.

    Always 200 — the body indicates which plans exist. An empty list
    is valid for the enterprise frame which never lists plans publicly.
    """
    service = BillingService(request.app)
    plans = service.list_plans()
    return PlansResponse(
        provider=service.provider_name,
        plans=[
            PlanOut(
                id=p.id,
                name=p.name,
                interval=p.interval.value,
                amount_cents=p.amount_cents,
                currency=p.currency,
                description=p.description,
                trial_days=p.trial_days,
                features=list(p.features),
            )
            for p in plans
        ],
    )


@router.post("/webhook")
async def billing_webhook(
    request: Request,
    x_billing_signature: str = Header(default="", alias="X-Billing-Signature"),
) -> Dict[str, Any]:
    """Receive and verify a webhook delivery from any provider.

    Returns 202 Accepted on successful verification. The body of the
    delivery is read as raw bytes so HMAC signatures are computed
    against the exact bytes the provider signed.
    """
    payload = await request.body()
    service = BillingService(request.app)
    try:
        event = service.verify_webhook(
            payload=payload, signature_header=x_billing_signature
        )
    except BillingProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        ) from exc
    except BillingProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {
        "received": True,
        "type": event.type,
        "provider": service.provider_name,
    }


__all__ = ["router"]