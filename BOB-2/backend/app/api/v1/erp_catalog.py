"""Tenant-scoped ERP accounting catalog HTTP component."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value
from app.security.tenant_scope import current_organization_id

router = APIRouter()


@router.get("/accounts")
def get_accounts(db_session: Session = Depends(get_db), company_id: Optional[int] = None):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == current_organization_id(required=True),
        ERPConnection.is_active == True
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

        effective_company_id = company_id
        if not effective_company_id:
            users = erp.execute_kw(
                "res.users",
                "search_read",
                [[["login", "=", username]]],
                {"fields": ["company_id"], "limit": 1}
            )
            effective_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        domain = []
        if effective_company_id:
            domain.append(["company_ids", "in", [effective_company_id]])

        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [domain],
            {
                "fields": ["id", "code", "name"],
                "order": "code asc",
                "limit": 1000,
            }
        )
        return accounts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch accounts: {str(e)}")


@router.get("/analytic-accounts")
def get_analytic_accounts(db_session: Session = Depends(get_db), company_id: Optional[int] = None):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == current_organization_id(required=True),
        ERPConnection.is_active == True
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

        domain: list = [["active", "=", True]]
        if company_id:
            domain.append(["company_id", "=", company_id])
        analytic_accounts = erp.execute_kw(
            "account.analytic.account",
            "search_read",
            [domain],
            {"fields": ["id", "name"], "order": "name asc", "limit": 1000},
        )
        return analytic_accounts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch analytic accounts: {str(e)}")


@router.get("/attachment/{attachment_id}")
def get_attachment(attachment_id: int, db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == current_organization_id(required=True),
        ERPConnection.is_active == True
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

        attachment = erp.execute_kw(
            "ir.attachment",
            "search_read",
            [[["id", "=", attachment_id]]],
            {"fields": ["name", "datas", "mimetype"], "limit": 1}
        )

        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found in Odoo.")

        att_data = attachment[0]
        name = att_data.get("name") or "attachment"
        datas_b64 = att_data.get("datas")
        mimetype = att_data.get("mimetype") or "application/octet-stream"

        if not datas_b64:
            raise HTTPException(status_code=404, detail="Attachment contains no data.")

        import base64
        from fastapi.responses import Response
        file_bytes = base64.b64decode(datas_b64)

        return Response(content=file_bytes, media_type=mimetype, headers={
            "Content-Disposition": f"inline; filename={name}"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch attachment: {str(e)}")


@router.get("/journals")
def get_journals(db_session: Session = Depends(get_db), company_id: Optional[int] = None):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == current_organization_id(required=True),
        ERPConnection.is_active == True
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

        effective_company_id = company_id
        if not effective_company_id:
            users = erp.execute_kw(
                "res.users",
                "search_read",
                [[["login", "=", username]]],
                {"fields": ["company_id"], "limit": 1}
            )
            effective_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        domain = []
        if effective_company_id:
            domain.append(["company_id", "=", effective_company_id])

        journals = erp.execute_kw(
            "account.journal",
            "search_read",
            [domain],
            {
                "fields": ["id", "code", "name", "type"],
                "limit": 100,
            }
        )
        return journals
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch journals: {str(e)}")
