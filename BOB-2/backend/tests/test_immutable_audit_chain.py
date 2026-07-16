"""Stage 13 regressions for immutable tamper-evident audit events."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.models.core import AuditLog
from app.security.audit_chain import AuditLogMutationError, GENESIS_HASH
from app.services.audit_integrity import verify_tenant_audit_chain


def _event(organization_id: int, action: str, user_id: int | None = None) -> AuditLog:
    return AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        entity_type="test",
        entity_id=action,
        ip_address="127.0.0.1",
        details={"action": action, "amount": "0.30"},
    )


def test_audit_events_are_chained_per_tenant(db, seeded_user):
    first = _event(1, "audit-first", seeded_user["id"])
    second = _event(1, "audit-second", seeded_user["id"])
    db.add_all([first, second])
    db.commit()
    db.refresh(first)
    db.refresh(second)

    assert first.scope_key == "org:1"
    assert first.sequence_number == 1
    assert first.previous_hash == GENESIS_HASH
    assert len(first.event_hash) == 64
    assert second.sequence_number == 2
    assert second.previous_hash == first.event_hash
    assert second.event_hash != first.event_hash

    result = verify_tenant_audit_chain(db, 1)
    assert result["valid"] is True
    assert result["events_checked"] >= 2
    assert result["last_hash"] == second.event_hash


def test_audit_chain_is_independent_between_tenants(db):
    first = _event(1, "tenant-one")
    second = _event(2, "tenant-two")
    db.add_all([first, second])
    db.commit()
    db.refresh(first)
    db.refresh(second)

    assert first.scope_key == "org:1"
    assert second.scope_key == "org:2"
    assert first.sequence_number == 1
    assert second.sequence_number == 1
    assert first.previous_hash == GENESIS_HASH
    assert second.previous_hash == GENESIS_HASH
    assert verify_tenant_audit_chain(db, 1)["valid"] is True
    assert verify_tenant_audit_chain(db, 2)["valid"] is True


def test_orm_update_and_delete_fail_before_flush(db):
    event = _event(1, "immutable-orm")
    db.add(event)
    db.commit()

    event.action = "tampered"
    try:
        db.flush()
    except AuditLogMutationError as exc:
        assert "append-only" in str(exc)
    else:
        raise AssertionError("AuditLog ORM update unexpectedly succeeded")
    db.rollback()

    event = db.query(AuditLog).filter(AuditLog.action == "immutable-orm").one()
    db.delete(event)
    try:
        db.flush()
    except AuditLogMutationError as exc:
        assert "append-only" in str(exc)
    else:
        raise AssertionError("AuditLog ORM delete unexpectedly succeeded")
    db.rollback()


def test_database_triggers_block_direct_update_and_delete(db):
    event = _event(1, "immutable-trigger")
    db.add(event)
    db.commit()

    try:
        db.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"),
            {"id": event.id},
        )
        db.commit()
    except DatabaseError as exc:
        db.rollback()
        assert "append-only" in str(exc).lower()
    else:
        raise AssertionError("Database UPDATE trigger did not reject mutation")

    try:
        db.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": event.id})
        db.commit()
    except DatabaseError as exc:
        db.rollback()
        assert "append-only" in str(exc).lower()
    else:
        raise AssertionError("Database DELETE trigger did not reject mutation")


def test_integrity_endpoint_is_permission_and_tenant_scoped(client, seeded_user, db):
    event = _event(1, "integrity-endpoint", seeded_user["id"])
    db.add(event)
    db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_user["email"], "password": seeded_user["password"]},
        headers={"User-Agent": "audit-integrity-test"},
    )
    assert login.status_code == 200, login.text
    response = client.get(
        "/api/v1/system/audit-integrity",
        headers={
            "Authorization": f"Bearer {login.json()['access_token']}",
            "User-Agent": "audit-integrity-test",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["organization_id"] == 1
    assert payload["scope_key"] == "org:1"
    assert payload["valid"] is True
    assert "details" not in payload


def test_verifier_detects_out_of_band_chain_corruption(db):
    event = _event(1, "detect-corruption")
    db.add(event)
    db.commit()

    # Drop the local SQLite trigger only inside this isolated test to emulate a
    # privileged out-of-band actor. Verification must still detect the change.
    if db.bind.dialect.name != "sqlite":
        return
    db.execute(text("DROP TRIGGER trg_audit_logs_no_update"))
    db.execute(
        text("UPDATE audit_logs SET details = :details WHERE id = :id"),
        {"details": '{"tampered":true}', "id": event.id},
    )
    db.commit()
    db.expire_all()

    result = verify_tenant_audit_chain(db, 1)
    assert result["valid"] is False
    assert result["failure_code"] == "event_hash_mismatch"
    assert result["first_invalid_sequence"] == event.sequence_number
