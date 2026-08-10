"""ERP connection and discovery HTTP component.

This router owns connection lifecycle concerns only. Document processing, partner
matching, and accounting workflows live in their own ERP components.
"""

import json
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.discovery import load_financial_kb, run_discovery_orchestrator
from app.erp.factory import get_erp_provider
from app.erp.odoo_cache import invalidate as invalidate_odoo_cache
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value, encrypt_value
from app.security.tenant_scope import current_organization_id

router = APIRouter()


class ERPConnectionRequest(BaseModel):
    provider: str = Field(default="odoo")
    url: str
    db: str
    username: str
    password: str


class ERPConnectionResponse(BaseModel):
    id: int
    provider: str
    url: str
    db: str
    username: str
    is_active: bool


@dataclass(frozen=True)
class SavedERPCredentials:
    connection: ERPConnection
    username: str
    password: str

    def provider(self):
        return get_erp_provider(
            provider=self.connection.provider,
            url=self.connection.base_url,
            db=self.connection.database_name or "",
            username=self.username,
            password=self.password,
        )


def _active_connection(db: Session) -> ERPConnection:
    connection = db.query(ERPConnection).filter(
        ERPConnection.organization_id == current_organization_id(required=True),
        ERPConnection.is_active.is_(True),
    ).first()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No saved active ERP connection found.",
        )
    return connection


def _saved_credentials(db: Session) -> SavedERPCredentials:
    connection = _active_connection(db)
    try:
        secret = json.loads(decrypt_value(connection.encrypted_secret_ref))
        return SavedERPCredentials(
            connection=connection,
            username=secret.get("username", ""),
            password=secret.get("password", ""),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt connection credentials.",
        ) from exc


@router.post("/test-connection")
def test_erp_connection(payload: ERPConnectionRequest):
    try:
        provider = get_erp_provider(
            provider=payload.provider,
            url=payload.url,
            db=payload.db,
            username=payload.username,
            password=payload.password,
        )
        return provider.test_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection test failed: {exc}",
        ) from exc


@router.post("/connection", response_model=ERPConnectionResponse)
def save_erp_connection(payload: ERPConnectionRequest, db: Session = Depends(get_db)):
    try:
        provider = get_erp_provider(
            provider=payload.provider,
            url=payload.url,
            db=payload.db,
            username=payload.username,
            password=payload.password,
        )
        if not provider.test_connection().get("connected"):
            raise ValueError("Authentication failed on the ERP provider.")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot save connection: verification failed ({exc})",
        ) from exc

    organization_id = current_organization_id(required=True)
    encrypted_secret = encrypt_value(json.dumps({
        "username": payload.username,
        "password": payload.password,
    }))
    connection = db.query(ERPConnection).filter(
        ERPConnection.organization_id == organization_id,
    ).first()
    if connection is None:
        connection = ERPConnection(
            organization_id=organization_id,
            auth_type="password",
        )
        db.add(connection)

    connection.provider = payload.provider
    connection.base_url = payload.url
    connection.database_name = payload.db
    connection.encrypted_secret_ref = encrypted_secret
    connection.is_active = True
    db.commit()
    db.refresh(connection)
    invalidate_odoo_cache(connection.base_url, connection.database_name or "")

    return ERPConnectionResponse(
        id=connection.id,
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=payload.username,
        is_active=connection.is_active,
    )


@router.get("/connection", response_model=ERPConnectionResponse)
def get_erp_connection(db: Session = Depends(get_db)):
    connection = _active_connection(db)
    try:
        username = json.loads(decrypt_value(connection.encrypted_secret_ref)).get("username", "")
    except Exception:
        username = ""
    return ERPConnectionResponse(
        id=connection.id,
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=username,
        is_active=connection.is_active,
    )


@router.post("/test-saved")
def test_saved_connection(db: Session = Depends(get_db)):
    credentials = _saved_credentials(db)
    try:
        return credentials.provider().test_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection test on saved credentials failed: {exc}",
        ) from exc


@router.get("/company-info-saved")
def get_saved_company_info(db: Session = Depends(get_db)):
    credentials = _saved_credentials(db)
    try:
        return credentials.provider().get_company_info()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch company info: {exc}",
        ) from exc


@router.get("/companies")
def list_companies(db: Session = Depends(get_db)):
    try:
        credentials = _saved_credentials(db)
        companies = credentials.provider().execute_kw(
            "res.company",
            "search_read",
            [[]],
            {"fields": ["id", "name", "currency_id"], "order": "id asc", "limit": 50},
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return []
        return []
    except Exception:
        return []
    return [
        {
            "id": company["id"],
            "name": company["name"],
            "currency": company.get("currency_id", [None, ""])[1]
            if isinstance(company.get("currency_id"), list)
            else "",
        }
        for company in companies
    ]


@router.post("/discover")
def trigger_erp_discovery(db: Session = Depends(get_db)):
    try:
        return run_discovery_orchestrator(_saved_credentials(db).provider())
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            exc.detail = "No saved active ERP connection found. Please connect to an ERP first."
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ERP Discovery failed: {exc}",
        ) from exc


@router.get("/discovery")
def get_discovered_kb():
    knowledge_base = load_financial_kb()
    if not knowledge_base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No discovered financial structure found. Please trigger discovery first.",
        )
    return knowledge_base
