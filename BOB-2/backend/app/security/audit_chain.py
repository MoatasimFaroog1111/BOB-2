"""Canonical hashing primitives for append-only audit events."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

AUDIT_EVENT_VERSION = 1
GENESIS_HASH = "0" * 64


class AuditLogMutationError(RuntimeError):
    """Raised when application code attempts to mutate an audit event."""


def audit_scope_key(organization_id: int | None) -> str:
    if organization_id is None:
        return "system"
    value = int(organization_id)
    if value <= 0:
        raise ValueError("Audit organization identifiers must be positive.")
    return f"org:{value}"


def advisory_lock_id(scope_key: str) -> int:
    raw = hashlib.sha256(scope_key.encode("utf-8")).digest()[:8]
    return int.from_bytes(raw, byteorder="big", signed=True)


def utc_naive(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("Non-finite audit values are forbidden.")
        return format(Decimal(str(value)), "f")
    if isinstance(value, datetime):
        return utc_naive(value).isoformat(timespec="microseconds") + "Z"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_audit_event_hash(
    *,
    scope_key: str,
    sequence_number: int,
    previous_hash: str,
    organization_id: int | None,
    user_id: int | None,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    ip_address: str | None,
    details: dict | None,
    created_at: datetime,
    event_version: int = AUDIT_EVENT_VERSION,
) -> str:
    payload = {
        "event_version": int(event_version),
        "scope_key": scope_key,
        "sequence_number": int(sequence_number),
        "previous_hash": previous_hash,
        "organization_id": organization_id,
        "user_id": user_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "ip_address": ip_address,
        "details": details,
        "created_at": utc_naive(created_at),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify_audit_rows(
    rows: Iterable[Any],
    *,
    scope_key: str,
    head_sequence: int,
    head_hash: str,
) -> dict[str, Any]:
    expected_sequence = 1
    expected_previous_hash = GENESIS_HASH
    checked = 0

    for row in rows:
        checked += 1
        row_sequence = int(row.sequence_number)
        if row.scope_key != scope_key:
            return _failure(checked, row_sequence, "scope_key_mismatch")
        if row_sequence != expected_sequence:
            return _failure(checked, row_sequence, "sequence_gap")
        if row.previous_hash != expected_previous_hash:
            return _failure(checked, row_sequence, "previous_hash_mismatch")
        if int(row.event_version) != AUDIT_EVENT_VERSION:
            return _failure(checked, row_sequence, "unsupported_event_version")

        calculated = compute_audit_event_hash(
            scope_key=row.scope_key,
            sequence_number=row_sequence,
            previous_hash=row.previous_hash,
            organization_id=row.organization_id,
            user_id=row.user_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            ip_address=row.ip_address,
            details=row.details,
            created_at=row.created_at,
            event_version=row.event_version,
        )
        if calculated != row.event_hash:
            return _failure(checked, row_sequence, "event_hash_mismatch")

        expected_previous_hash = row.event_hash
        expected_sequence += 1

    expected_head_sequence = expected_sequence - 1
    if int(head_sequence) != expected_head_sequence:
        return _failure(checked, expected_head_sequence, "head_sequence_mismatch")
    expected_head_hash = expected_previous_hash if checked else GENESIS_HASH
    if head_hash != expected_head_hash:
        return _failure(checked, expected_head_sequence, "head_hash_mismatch")

    return {
        "valid": True,
        "scope_key": scope_key,
        "events_checked": checked,
        "last_sequence": expected_head_sequence,
        "last_hash": expected_head_hash,
        "failure_code": None,
        "first_invalid_sequence": None,
    }


def _failure(checked: int, sequence: int, code: str) -> dict[str, Any]:
    return {
        "valid": False,
        "events_checked": checked,
        "last_sequence": max(sequence - 1, 0),
        "last_hash": None,
        "failure_code": code,
        "first_invalid_sequence": sequence,
    }
