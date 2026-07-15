from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.core import AuthSession
from app.models.session_security import (
    AuthSessionRotationState,
    AuthSessionSecurityEvent,
)

_FORBIDDEN_EVENT_KEYS = ("token", "jti", "hash", "password", "secret", "credential")


def user_agent_hash(user_agent: str | None) -> str | None:
    value = (user_agent or "").strip()
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_event_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in _FORBIDDEN_EVENT_KEYS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe or None


def record_session_event(
    db: Session,
    *,
    event_type: str,
    outcome: str,
    organization_id: int | None,
    user_id: int | None,
    session_id: str | None,
    family_id: str | None,
    generation: int | None,
    ip_address: str | None,
    user_agent: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuthSessionSecurityEvent(
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            family_id=family_id,
            event_type=event_type[:64],
            outcome=outcome[:32],
            generation=generation,
            ip_address=(ip_address or "")[:100] or None,
            user_agent_hash=user_agent_hash(user_agent),
            event_metadata=_safe_event_metadata(metadata),
        )
    )


def create_rotation_state(db: Session, *, session_id: str, family_id: str) -> None:
    db.add(
        AuthSessionRotationState(
            session_id=session_id,
            family_id=family_id,
            generation=0,
        )
    )


def load_rotation_state_for_update(
    db: Session,
    *,
    session_id: str,
    family_id: str,
) -> AuthSessionRotationState | None:
    return db.execute(
        select(AuthSessionRotationState)
        .where(
            AuthSessionRotationState.session_id == session_id,
            AuthSessionRotationState.family_id == family_id,
        )
        .with_for_update()
    ).scalar_one_or_none()


def claim_refresh_generation(
    db: Session,
    *,
    session_id: str,
    family_id: str,
    expected_generation: int,
    rotated_at: datetime,
) -> bool:
    """Compare-and-swap the generation; exactly one concurrent caller can win."""

    result = db.execute(
        update(AuthSessionRotationState)
        .where(
            AuthSessionRotationState.session_id == session_id,
            AuthSessionRotationState.family_id == family_id,
            AuthSessionRotationState.generation == expected_generation,
        )
        .values(
            generation=expected_generation + 1,
            last_rotated_at=rotated_at,
        )
    )
    return result.rowcount == 1


def revoke_family(
    db: Session,
    *,
    family_id: str,
    reason: str,
    event_type: str,
    organization_id: int | None,
    user_id: int | None,
    session_id: str | None,
    generation: int | None,
    ip_address: str | None,
    user_agent: str | None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    now = datetime.utcnow()
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.family_id == family_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=now,
            revocation_reason=reason[:100],
        )
    )
    record_session_event(
        db,
        event_type=event_type,
        outcome="denied",
        organization_id=organization_id,
        user_id=user_id,
        session_id=session_id,
        family_id=family_id,
        generation=generation,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata,
    )
    if commit:
        db.commit()
