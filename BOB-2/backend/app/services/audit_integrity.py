"""Verification service for tenant-scoped tamper-evident audit chains."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.core import AuditLog, AuditLogChainHead
from app.security.audit_chain import GENESIS_HASH, audit_scope_key, verify_audit_rows


def verify_tenant_audit_chain(db: Session, organization_id: int) -> dict:
    organization_id = int(organization_id)
    if organization_id <= 0:
        raise ValueError("A positive organization identifier is required.")

    scope_key = audit_scope_key(organization_id)
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.organization_id == organization_id,
            AuditLog.scope_key == scope_key,
        )
        .order_by(AuditLog.sequence_number.asc(), AuditLog.id.asc())
        .all()
    )
    head = db.get(AuditLogChainHead, scope_key)
    head_sequence = int(head.last_sequence) if head else 0
    head_hash = head.last_hash if head else GENESIS_HASH
    result = verify_audit_rows(
        rows,
        scope_key=scope_key,
        head_sequence=head_sequence,
        head_hash=head_hash,
    )
    result["organization_id"] = organization_id
    result["head_present"] = head is not None
    return result
