"""add atomic refresh rotation state and security events

Revision ID: a8c4e1f2d670
Revises: f3a9d2c7b410
Create Date: 2026-07-15 13:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8c4e1f2d670"
down_revision: str | None = "f3a9d2c7b410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_session_rotation_states",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_rotated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name="fk_auth_session_rotation_states_session_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("session_id", name="uq_auth_session_rotation_states_session"),
    )
    op.create_index(
        "ix_auth_session_rotation_states_family_id",
        "auth_session_rotation_states",
        ["family_id"],
        unique=False,
    )

    op.create_table(
        "auth_session_security_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("family_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=100), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "organization_id",
        "user_id",
        "session_id",
        "family_id",
        "event_type",
        "outcome",
    ):
        op.create_index(
            f"ix_auth_session_security_events_{column}",
            "auth_session_security_events",
            [column],
            unique=False,
        )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO auth_session_rotation_states
                (session_id, family_id, generation, created_at, updated_at)
            SELECT id, family_id, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
              FROM auth_sessions
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE auth_sessions
               SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
                   revocation_reason = CASE
                       WHEN revoked_at IS NULL THEN 'atomic_rotation_migration'
                       ELSE revocation_reason
                   END
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO auth_session_security_events
                (organization_id, user_id, session_id, family_id, event_type,
                 outcome, generation, created_at, updated_at)
            SELECT organization_id, user_id, id, family_id,
                   'atomic_rotation_migration', 'revoked', 0,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
              FROM auth_sessions
             WHERE revocation_reason = 'atomic_rotation_migration'
            """
        )
    )


def downgrade() -> None:
    for column in (
        "outcome",
        "event_type",
        "family_id",
        "session_id",
        "user_id",
        "organization_id",
    ):
        op.drop_index(
            f"ix_auth_session_security_events_{column}",
            table_name="auth_session_security_events",
        )
    op.drop_table("auth_session_security_events")
    op.drop_index(
        "ix_auth_session_rotation_states_family_id",
        table_name="auth_session_rotation_states",
    )
    op.drop_table("auth_session_rotation_states")
