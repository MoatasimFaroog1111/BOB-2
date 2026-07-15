from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.dependencies import require_permission
from app.services.tenant_erp import resolve_tenant_erp

router = APIRouter()


@router.get("/partners")
def get_company_partners(
    db_session: Session = Depends(get_db),
    company_id: Optional[int] = None,
    principal: dict = Depends(require_permission("view_financials")),
):
    """Return Odoo customers and vendors from this tenant's ERP connection."""

    context = resolve_tenant_erp(db_session, principal)
    erp = context.provider

    domain = [
        ("active", "=", True),
        "|",
        ("customer_rank", ">", 0),
        ("supplier_rank", ">", 0),
    ]
    if company_id:
        domain.extend(["|", ("company_id", "=", False), ("company_id", "=", company_id)])

    try:
        try:
            partners = erp.execute_kw(
                "res.partner",
                "search_read",
                [domain],
                {
                    "fields": [
                        "id",
                        "name",
                        "customer_rank",
                        "supplier_rank",
                        "company_id",
                        "vat",
                        "email",
                        "phone",
                    ],
                    "order": "name asc",
                    "limit": 5000,
                },
            )
        except Exception:
            fallback_domain = [("active", "=", True)]
            if company_id:
                fallback_domain.extend(
                    ["|", ("company_id", "=", False), ("company_id", "=", company_id)]
                )
            partners = erp.execute_kw(
                "res.partner",
                "search_read",
                [fallback_domain],
                {
                    "fields": ["id", "name", "company_id", "vat", "email", "phone"],
                    "order": "name asc",
                    "limit": 5000,
                },
            )

        normalized = []
        for partner in partners:
            name = partner.get("name") or ""
            if not name:
                continue
            normalized.append(
                {
                    "id": partner.get("id"),
                    "name": name,
                    "customer_rank": int(partner.get("customer_rank") or 0),
                    "supplier_rank": int(partner.get("supplier_rank") or 0),
                    "company_id": partner.get("company_id"),
                    "vat": partner.get("vat") or "",
                    "email": partner.get("email") or "",
                    "phone": partner.get("phone") or "",
                }
            )
        return normalized
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch company partners from Odoo: {type(exc).__name__}",
        ) from exc
