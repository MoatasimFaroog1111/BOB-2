"""add immutable tamper-evident audit chain

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
