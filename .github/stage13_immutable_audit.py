from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "BOB-2" / "backend"
APP = BACKEND / "app"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


AUDIT_CHAIN = '''"""Canonical hashing primitives for append-only audit events."""

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
'''


AUDIT_INTEGRITY = '''"""Verification service for tenant-scoped tamper-evident audit chains."""

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
'''


MIGRATION = '''"""add immutable tamper-evident audit chain

Revision ID: b4e2c7d9f130
Revises: a8c4e1f2d670
"""

from __future__ import annotations

import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa

from app.security.audit_chain import (
    AUDIT_EVENT_VERSION,
    GENESIS_HASH,
    audit_scope_key,
    compute_audit_event_hash,
    utc_naive,
)

revision = "b4e2c7d9f130"
down_revision = "a8c4e1f2d670"
branch_labels = None
depends_on = None


def _details(value):
    if value is None or isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {"legacy_value": value}
        return parsed if isinstance(parsed, dict) else {"legacy_value": parsed}
    return {"legacy_value": str(value)}


def _created_at(value) -> datetime:
    if isinstance(value, datetime):
        return utc_naive(value)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return utc_naive(datetime.fromisoformat(normalized))
        except ValueError:
            pass
    raise RuntimeError("An existing audit event has an invalid created_at value.")


def _create_append_only_triggers(bind) -> None:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION guardian_prevent_audit_log_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs")
        op.execute(
            """
            CREATE TRIGGER trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION guardian_prevent_audit_log_mutation()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION guardian_prevent_audit_log_mutation()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs is append-only');
            END
            """
        )


def _drop_append_only_triggers(bind) -> None:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS guardian_prevent_audit_log_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete")


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "audit_log_chain_heads",
        sa.Column("scope_key", sa.String(length=80), primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.add_column("audit_logs", sa.Column("scope_key", sa.String(length=80), nullable=True))
    op.add_column("audit_logs", sa.Column("sequence_number", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("previous_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("event_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "audit_logs",
        sa.Column("event_version", sa.Integer(), nullable=True),
    )

    rows = bind.execute(
        sa.text(
            """
            SELECT id, organization_id, user_id, action, entity_type, entity_id,
                   ip_address, details, created_at
              FROM audit_logs
             ORDER BY CASE WHEN organization_id IS NULL THEN 0 ELSE 1 END,
                      organization_id, id
            """
        )
    ).mappings().all()

    state: dict[str, tuple[int, str]] = {}
    for row in rows:
        scope_key = audit_scope_key(row["organization_id"])
        sequence, previous_hash = state.get(scope_key, (0, GENESIS_HASH))
        sequence += 1
        created_at = _created_at(row["created_at"])
        details = _details(row["details"])
        event_hash = compute_audit_event_hash(
            scope_key=scope_key,
            sequence_number=sequence,
            previous_hash=previous_hash,
            organization_id=row["organization_id"],
            user_id=row["user_id"],
            action=row["action"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            ip_address=row["ip_address"],
            details=details,
            created_at=created_at,
            event_version=AUDIT_EVENT_VERSION,
        )
        bind.execute(
            sa.text(
                """
                UPDATE audit_logs
                   SET scope_key = :scope_key,
                       sequence_number = :sequence_number,
                       previous_hash = :previous_hash,
                       event_hash = :event_hash,
                       event_version = :event_version
                 WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "scope_key": scope_key,
                "sequence_number": sequence,
                "previous_hash": previous_hash,
                "event_hash": event_hash,
                "event_version": AUDIT_EVENT_VERSION,
            },
        )
        state[scope_key] = (sequence, event_hash)

    now = utc_naive()
    for scope_key, (last_sequence, last_hash) in state.items():
        bind.execute(
            sa.text(
                """
                INSERT INTO audit_log_chain_heads
                    (scope_key, last_sequence, last_hash, updated_at)
                VALUES
                    (:scope_key, :last_sequence, :last_hash, :updated_at)
                """
            ),
            {
                "scope_key": scope_key,
                "last_sequence": last_sequence,
                "last_hash": last_hash,
                "updated_at": now,
            },
        )

    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column("scope_key", existing_type=sa.String(length=80), nullable=False)
        batch.alter_column("sequence_number", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("previous_hash", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("event_hash", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("event_version", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint(
            "uq_audit_logs_scope_sequence",
            ["scope_key", "sequence_number"],
        )
        batch.create_unique_constraint("uq_audit_logs_event_hash", ["event_hash"])
        batch.create_index("ix_audit_logs_scope_key", ["scope_key"])
        batch.create_index("ix_audit_logs_event_hash", ["event_hash"])

    _create_append_only_triggers(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _drop_append_only_triggers(bind)
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_index("ix_audit_logs_event_hash")
        batch.drop_index("ix_audit_logs_scope_key")
        batch.drop_constraint("uq_audit_logs_event_hash", type_="unique")
        batch.drop_constraint("uq_audit_logs_scope_sequence", type_="unique")
        batch.drop_column("event_version")
        batch.drop_column("event_hash")
        batch.drop_column("previous_hash")
        batch.drop_column("sequence_number")
        batch.drop_column("scope_key")
    op.drop_table("audit_log_chain_heads")
'''


TESTS = '''"""Stage 13 regressions for immutable tamper-evident audit events."""

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
'''


GUARD = '''"""Static guard for immutable audit-chain controls."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


core = source("app/models/core.py")
chain = source("app/security/audit_chain.py")
integrity = source("app/services/audit_integrity.py")
system = source("app/api/v1/system.py")
migration = source("migrations/versions/b4e2c7d9f130_add_immutable_audit_chain.py")
tests = source("tests/test_immutable_audit_chain.py")

for marker in (
    "class AuditLogChainHead",
    "scope_key",
    "sequence_number",
    "previous_hash",
    "event_hash",
    "event_version",
    "@event.listens_for(Session, \"before_flush\")",
    "AuditLogMutationError",
    "pg_advisory_xact_lock",
    "trg_audit_logs_no_update",
    "trg_audit_logs_no_delete",
):
    require(marker in core, f"Audit model control missing: {marker}")

for marker in (
    "canonical_json",
    "compute_audit_event_hash",
    "verify_audit_rows",
    "GENESIS_HASH",
):
    require(marker in chain, f"Audit hashing control missing: {marker}")

require("verify_tenant_audit_chain" in integrity, "Tenant audit verifier missing")
require('@router.get("/audit-integrity")' in system, "Audit-integrity endpoint missing")
require('require_permission("view_audit_logs")' in system, "Audit-integrity endpoint permission missing")
require('revision = "b4e2c7d9f130"' in migration, "Audit migration revision changed")
require('down_revision = "a8c4e1f2d670"' in migration, "Audit migration parent changed")
require("UPDATE audit_logs" in migration and "DELETE ON audit_logs" in migration, "Append-only migration triggers missing")
for marker in (
    "test_database_triggers_block_direct_update_and_delete",
    "test_verifier_detects_out_of_band_chain_corruption",
    "test_integrity_endpoint_is_permission_and_tenant_scoped",
):
    require(marker in tests, f"Audit regression missing: {marker}")

print("Immutable audit-chain source guard passed.")
'''


WORKFLOW = '''name: Immutable audit chain

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

permissions:
  contents: read

concurrency:
  group: immutable-audit-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  immutable-audit:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: BOB-2/backend
    env:
      APP_ENV: test
      DATABASE_URL: sqlite:///./ci-immutable-audit.db
      SECRET_KEY: ci-only-secret-key-that-is-longer-than-thirty-two-characters
      SECRET_STORE_PROVIDER: memory
      LOCAL_LLM_ENABLED: "false"
      EXTERNAL_LLM_ENABLED: "false"
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: BOB-2/backend/requirements.lock
      - name: Install hash-locked dependencies
        run: pip install --quiet --require-hashes -r requirements.lock
      - name: Compile immutable audit paths
        run: python -m compileall -q app/security/audit_chain.py app/services/audit_integrity.py app/models/core.py tests/test_immutable_audit_chain.py
      - name: Enforce immutable audit source boundaries
        run: python scripts/check_immutable_audit_chain.py
      - name: Run immutable audit regressions
        run: pytest -q tests/test_immutable_audit_chain.py tests/test_security.py tests/test_tenant_isolation_completion.py
'''


MIGRATION_WORKFLOW = '''name: Database migrations

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

permissions:
  contents: read

concurrency:
  group: migrations-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  migration-round-trip:
    name: Alembic — Upgrade, Downgrade, Upgrade
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: BOB-2/backend
    env:
      APP_ENV: test
      DATABASE_URL: sqlite:///./ci-migrations.db
      SECRET_KEY: ci-only-secret-key-that-is-longer-than-thirty-two-characters
      SECRET_STORE_PROVIDER: memory
      LOCAL_LLM_ENABLED: "false"
      EXTERNAL_LLM_ENABLED: "false"
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: BOB-2/backend/requirements.lock
      - name: Install hash-locked dependencies
        run: pip install --quiet --require-hashes -r requirements.lock
      - name: Verify one Alembic head
        run: |
          test "$(alembic heads | grep -c '(head)')" -eq 1
          alembic heads | grep 'b4e2c7d9f130'
      - name: Prepare parent schema with legacy audit data
        run: |
          rm -f ci-migrations.db
          alembic upgrade a8c4e1f2d670
          python - <<'PY'
          import sqlite3

          connection = sqlite3.connect("ci-migrations.db")
          try:
              connection.execute(
                  """
                  INSERT INTO organizations
                      (id, name, legal_name, country, is_active, created_at, updated_at)
                  VALUES
                      (999, 'Audit Migration', 'Audit Migration', 'SA', 1,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                  """
              )
              connection.execute(
                  """
                  INSERT INTO users
                      (id, organization_id, email, full_name, role, hashed_password,
                       is_active, security_version, security_changed_at, created_at, updated_at)
                  VALUES
                      (999, 999, 'audit-migration@test.invalid', 'Audit Migration',
                       'owner', 'not-used', 1, 1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                  """
              )
              connection.execute(
                  """
                  INSERT INTO audit_logs
                      (organization_id, user_id, action, entity_type, entity_id,
                       ip_address, details, created_at, updated_at)
                  VALUES
                      (999, 999, 'legacy_audit_event', 'migration', '999',
                       '127.0.0.1', '{"legacy":true}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                  """
              )
              connection.commit()
          finally:
              connection.close()
          PY
      - name: Upgrade to immutable audit chain
        run: |
          alembic upgrade head
          python - <<'PY'
          import sqlite3

          connection = sqlite3.connect("ci-migrations.db")
          try:
              revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
              assert revision == "b4e2c7d9f130"
              tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
              assert "audit_log_chain_heads" in tables
              columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_logs)")}
              assert {"scope_key", "sequence_number", "previous_hash", "event_hash", "event_version"} <= columns
              event = connection.execute(
                  """
                  SELECT scope_key, sequence_number, previous_hash, event_hash, event_version
                    FROM audit_logs
                   WHERE action = 'legacy_audit_event'
                  """
              ).fetchone()
              assert event[0] == "org:999"
              assert event[1] == 1
              assert event[2] == "0" * 64
              assert len(event[3]) == 64
              assert event[4] == 1
              head = connection.execute(
                  "SELECT last_sequence, last_hash FROM audit_log_chain_heads WHERE scope_key = 'org:999'"
              ).fetchone()
              assert head == (1, event[3])
              triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
              assert {"trg_audit_logs_no_update", "trg_audit_logs_no_delete"} <= triggers
              try:
                  connection.execute("UPDATE audit_logs SET action = 'tampered' WHERE action = 'legacy_audit_event'")
              except sqlite3.DatabaseError as exc:
                  assert "append-only" in str(exc)
              else:
                  raise AssertionError("Audit UPDATE trigger did not fire")
          finally:
              connection.close()
          PY
      - name: Downgrade to parent and verify audit controls are removed
        run: |
          alembic downgrade a8c4e1f2d670
          python - <<'PY'
          import sqlite3

          connection = sqlite3.connect("ci-migrations.db")
          try:
              revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
              assert revision == "a8c4e1f2d670"
              tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
              assert "audit_log_chain_heads" not in tables
              columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_logs)")}
              assert "event_hash" not in columns
              triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
              assert "trg_audit_logs_no_update" not in triggers
              connection.execute("UPDATE audit_logs SET action = 'legacy_audit_event' WHERE entity_id = '999'")
              connection.commit()
          finally:
              connection.close()
          PY
      - name: Re-upgrade and verify immutable audit state
        run: |
          alembic upgrade head
          python - <<'PY'
          import sqlite3

          connection = sqlite3.connect("ci-migrations.db")
          try:
              assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "b4e2c7d9f130"
              event = connection.execute(
                  "SELECT sequence_number, previous_hash, event_hash FROM audit_logs WHERE entity_id = '999'"
              ).fetchone()
              assert event[0] == 1
              assert event[1] == "0" * 64
              assert len(event[2]) == 64
              assert connection.execute(
                  "SELECT COUNT(*) FROM audit_log_chain_heads WHERE scope_key = 'org:999'"
              ).fetchone()[0] == 1
          finally:
              connection.close()
          PY
'''


DOC = '''# Immutable tamper-evident audit chain

Stage 13 makes the central `audit_logs` table append-only and chains events per
organization.

## Write boundary

Every ORM `AuditLog` insert is sealed in the same database transaction. The
application derives the scope from `organization_id`, serializes writers for the
scope, allocates a monotonic sequence number, links the prior hash, and computes
a canonical SHA-256 event hash. Client-supplied chain fields are overwritten.

PostgreSQL uses a transaction-scoped advisory lock for each chain. SQLite keeps
the same deterministic behavior for tests and local development. Each tenant
has an independent chain; events with no tenant use the `system` chain.

## Immutability

Application-level flush guards reject ORM updates and deletes. Database triggers
reject direct SQL `UPDATE` and `DELETE`, so ordinary application/database roles
can only append. Unique scope/sequence and event-hash constraints prevent silent
duplication.

Migration `b4e2c7d9f130` deterministically backfills every historical audit row,
creates the current chain heads, then activates the mutation triggers.

## Verification

Authorized users with `view_audit_logs` may call:

`GET /api/v1/system/audit-integrity`

The response contains chain validity, event count, last sequence/hash, and a
safe failure code. It does not return event details. Verification recalculates
every event hash and checks sequence continuity, previous-hash links, and the
stored chain head.

## Trust boundary

This is database-enforced append-only storage and tamper evidence. It is not a
WORM archive against a PostgreSQL superuser who can disable triggers and rewrite
the complete chain and head. Production audit evidence should additionally be
exported or checkpointed to independently controlled append-only/WORM storage.
Telegram and external LLM execution remain disabled in production.
'''


def patch_core() -> None:
    path = APP / "models" / "core.py"
    text = read(path)
    text = text.replace(
        "    select,\n    update,\n",
        "    insert,\n    select,\n    text,\n    update,\n",
        1,
    )
    text = text.replace(
        "from sqlalchemy.orm import Mapped, mapped_column",
        "from sqlalchemy.orm import Mapped, Session, mapped_column",
        1,
    )
    text = text.replace(
        "from app.models.mixins import TimestampMixin\n",
        "from app.models.mixins import TimestampMixin\nfrom app.security.audit_chain import (\n    AUDIT_EVENT_VERSION,\n    GENESIS_HASH,\n    AuditLogMutationError,\n    advisory_lock_id,\n    audit_scope_key,\n    compute_audit_event_hash,\n    utc_naive,\n)\n",
        1,
    )
    old = '''class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
'''
    new = '''class AuditLogChainHead(Base):
    __tablename__ = "audit_log_chain_heads"

    scope_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False, default=GENESIS_HASH)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        UniqueConstraint("scope_key", "sequence_number", name="uq_audit_logs_scope_sequence"),
        UniqueConstraint("event_hash", name="uq_audit_logs_event_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scope_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=AUDIT_EVENT_VERSION)
'''
    if old not in text:
        raise RuntimeError("AuditLog model block changed unexpectedly")
    text = text.replace(old, new, 1)

    listener = '''

def _create_audit_append_only_triggers(target, connection, **_kwargs) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs is append-only');
            END
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs is append-only');
            END
            """
        )
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            """
            CREATE OR REPLACE FUNCTION guardian_prevent_audit_log_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs")
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION guardian_prevent_audit_log_mutation()
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION guardian_prevent_audit_log_mutation()
            """
        )


event.listen(AuditLog.__table__, "after_create", _create_audit_append_only_triggers)


@event.listens_for(Session, "before_flush")
def _seal_and_protect_audit_events(session: Session, _flush_context, _instances) -> None:
    for obj in tuple(session.deleted):
        if isinstance(obj, AuditLog):
            raise AuditLogMutationError("Audit events are append-only and cannot be deleted.")
    for obj in tuple(session.dirty):
        if isinstance(obj, AuditLog) and session.is_modified(obj, include_collections=True):
            raise AuditLogMutationError("Audit events are append-only and cannot be updated.")

    pending = [obj for obj in tuple(session.new) if isinstance(obj, AuditLog)]
    if not pending:
        return

    grouped: dict[str, list[AuditLog]] = {}
    for audit_event in pending:
        scope_key = audit_scope_key(audit_event.organization_id)
        grouped.setdefault(scope_key, []).append(audit_event)

    connection = session.connection()
    head_table = AuditLogChainHead.__table__
    for scope_key in sorted(grouped):
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": advisory_lock_id(scope_key)},
            )

        head = connection.execute(
            select(head_table.c.last_sequence, head_table.c.last_hash)
            .where(head_table.c.scope_key == scope_key)
            .with_for_update()
        ).first()
        sequence = int(head.last_sequence) if head else 0
        previous_hash = head.last_hash if head else GENESIS_HASH
        now = utc_naive()

        for audit_event in grouped[scope_key]:
            sequence += 1
            created_at = utc_naive(audit_event.created_at or now)
            audit_event.created_at = created_at
            audit_event.updated_at = audit_event.updated_at or created_at
            audit_event.scope_key = scope_key
            audit_event.sequence_number = sequence
            audit_event.previous_hash = previous_hash
            audit_event.event_version = AUDIT_EVENT_VERSION
            audit_event.event_hash = compute_audit_event_hash(
                scope_key=scope_key,
                sequence_number=sequence,
                previous_hash=previous_hash,
                organization_id=audit_event.organization_id,
                user_id=audit_event.user_id,
                action=audit_event.action,
                entity_type=audit_event.entity_type,
                entity_id=audit_event.entity_id,
                ip_address=audit_event.ip_address,
                details=audit_event.details,
                created_at=created_at,
                event_version=AUDIT_EVENT_VERSION,
            )
            previous_hash = audit_event.event_hash

        if head:
            connection.execute(
                update(head_table)
                .where(head_table.c.scope_key == scope_key)
                .values(last_sequence=sequence, last_hash=previous_hash, updated_at=now)
            )
        else:
            connection.execute(
                insert(head_table).values(
                    scope_key=scope_key,
                    last_sequence=sequence,
                    last_hash=previous_hash,
                    updated_at=now,
                )
            )
'''
    marker = "\n\n_USER_SECURITY_FIELDS = ("
    if marker not in text:
        raise RuntimeError("Core security event marker changed unexpectedly")
    text = text.replace(marker, listener + marker, 1)
    write(path, text)


def patch_models_init() -> None:
    path = APP / "models" / "__init__.py"
    text = read(path)
    text = text.replace("    AuditLog,\n", "    AuditLog,\n    AuditLogChainHead,\n", 1)
    text = text.replace('    "AuditLog",\n', '    "AuditLog",\n    "AuditLogChainHead",\n', 1)
    write(path, text)


def patch_system() -> None:
    path = APP / "api" / "v1" / "system.py"
    write(
        path,
        '''from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.security.dependencies import require_permission
from app.services.audit_integrity import verify_tenant_audit_chain

router = APIRouter()


@router.get("/status")
def system_status(
    current_user: dict = Depends(require_permission("manage_settings")),
):
    """Return detailed runtime status only to authorized administrators."""
    return {
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "status": "running",
        "api_version": "v1",
        "guardrails": "enabled",
        "human_approval": "required_for_financial_posting",
        "requested_by": current_user.get("sub"),
    }


@router.get("/audit-integrity")
def audit_integrity(
    current_user: dict = Depends(require_permission("view_audit_logs")),
    db: Session = Depends(get_db),
):
    """Recalculate the authenticated tenant's audit chain without disclosing events."""
    organization_id = current_user.get("organization_id")
    if not isinstance(organization_id, int) or organization_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated organization context is required.",
        )
    return verify_tenant_audit_chain(db, organization_id)
''',
    )


def patch_security_deployment() -> None:
    path = REPO / "BOB-2" / "SECURITY_DEPLOYMENT.md"
    text = read(path)
    marker = "Retain audit and security logs in append-only or centrally controlled storage with access restricted to authorized administrators and auditors."
    replacement = marker + '''

The central `audit_logs` table is database-enforced append-only after migration
`b4e2c7d9f130` and uses an independent tamper-evident SHA-256 chain per
organization. Authorized auditors can verify the current tenant at
`GET /api/v1/system/audit-integrity`. Export or checkpoint the resulting chain
head to independently controlled WORM storage because a database superuser is
outside the in-database trust boundary.'''
    if marker not in text:
        raise RuntimeError("Security deployment audit marker changed")
    write(path, text.replace(marker, replacement, 1))


def main() -> None:
    write(APP / "security" / "audit_chain.py", AUDIT_CHAIN)
    write(APP / "services" / "audit_integrity.py", AUDIT_INTEGRITY)
    write(BACKEND / "migrations" / "versions" / "b4e2c7d9f130_add_immutable_audit_chain.py", MIGRATION)
    write(BACKEND / "tests" / "test_immutable_audit_chain.py", TESTS)
    write(BACKEND / "scripts" / "check_immutable_audit_chain.py", GUARD)
    write(REPO / ".github" / "workflows" / "immutable-audit-chain.yml", WORKFLOW)
    write(REPO / ".github" / "workflows" / "migrations.yml", MIGRATION_WORKFLOW)
    write(REPO / "BOB-2" / "IMMUTABLE_AUDIT_CHAIN.md", DOC)
    patch_core()
    patch_models_init()
    patch_system()
    patch_security_deployment()

    for path in (
        APP / "security" / "audit_chain.py",
        APP / "services" / "audit_integrity.py",
        APP / "models" / "core.py",
        BACKEND / "migrations" / "versions" / "b4e2c7d9f130_add_immutable_audit_chain.py",
        BACKEND / "tests" / "test_immutable_audit_chain.py",
    ):
        ast.parse(read(path), filename=str(path))

    bootstrap = REPO / ".github" / "workflows" / "stage13-bootstrap.yml"
    if bootstrap.exists():
        bootstrap.unlink()
    Path(__file__).unlink()

    subprocess.run(["git", "config", "user.name", "guardian-stage13-bot"], cwd=REPO, check=True)
    subprocess.run(["git", "config", "user.email", "guardian-stage13-bot@users.noreply.github.com"], cwd=REPO, check=True)
    subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
    subprocess.run(["git", "commit", "-m", "make audit events append-only and tamper-evident"], cwd=REPO, check=True)
    subprocess.run(["git", "push", "origin", "HEAD:agent/immutable-audit-chain"], cwd=REPO, check=True)


if __name__ == "__main__":
    main()
