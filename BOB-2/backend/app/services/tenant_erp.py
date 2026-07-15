"""Central tenant-bound ERP connection resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value


@dataclass(frozen=True, slots=True)
class TenantERPContext:
    organization_id: int
    connection: ERPConnection
    provider: Any
    username: str


def organization_id_from_principal(principal: dict) -> int:
    organization_id = principal.get("organization_id")
    if not isinstance(organization_id, int) or organization_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user is not associated with an active organization.",
        )
    return organization_id


def load_tenant_erp_connection(
    db: Session,
    organization_id: int,
    *,
    require_active: bool = True,
) -> ERPConnection:
    query = db.query(ERPConnection).filter(
        ERPConnection.organization_id == organization_id,
    )
    if require_active:
        query = query.filter(ERPConnection.is_active.is_(True))
    connection = query.order_by(ERPConnection.id.asc()).first()
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ERP connection found for the authenticated organization.",
        )
    return connection


def resolve_tenant_erp(
    db: Session,
    principal: dict,
    *,
    require_active: bool = True,
) -> TenantERPContext:
    organization_id = organization_id_from_principal(principal)
    connection = load_tenant_erp_connection(
        db,
        organization_id,
        require_active=require_active,
    )
    if not connection.encrypted_secret_ref:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ERP credentials are unavailable from the centralized secret store.",
        )
    try:
        credentials = json.loads(decrypt_value(connection.encrypted_secret_ref))
        username = str(credentials["username"])
        password = str(credentials["password"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ERP credentials are unavailable from the centralized secret store.",
        ) from exc

    provider = get_erp_provider(
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=username,
        password=password,
    )
    return TenantERPContext(
        organization_id=organization_id,
        connection=connection,
        provider=provider,
        username=username,
    )
