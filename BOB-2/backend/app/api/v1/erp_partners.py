from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.core import ERPConnection
from app.erp.factory import get_erp_provider
from app.security.encryption import decrypt_value
import json

router = APIRouter()


@router.get("/partners")
def get_company_partners(db_session: Session = Depends(get_db), company_id: Optional[int] = None):
    """Return Odoo customers and vendors for the selected company.

    Shared Odoo contacts with company_id=False are also included because Odoo commonly
    stores usable customers/vendors as global contacts across companies.
    """
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True,
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        domain = [
            ("active", "=", True),
            "|",
            ("customer_rank", ">", 0),
            ("supplier_rank", ">", 0),
        ]
        if company_id:
            domain.extend(["|", ("company_id", "=", False), ("company_id", "=", company_id)])

        try:
            partners = erp.execute_kw(
                "res.partner",
                "search_read",
                [domain],
                {
                    "fields": ["id", "name", "customer_rank", "supplier_rank", "company_id", "vat", "email", "phone"],
                    "order": "name asc",
                    "limit": 5000,
                },
            )
        except Exception:
            fallback_domain = [("active", "=", True)]
            if company_id:
                fallback_domain.extend(["|", ("company_id", "=", False), ("company_id", "=", company_id)])
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch company partners from Odoo: {str(exc)}")
