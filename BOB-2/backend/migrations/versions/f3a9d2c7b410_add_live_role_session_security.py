"""add live role and security-version session invalidation

Revision ID: f3a9d2c7b410
Revises: e6b8c1d4a290
Create Date: 2026-07-15 13:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a9d2c7b410"
down_revision: str | None = "e6b8c1d4a290"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "security_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.add_column(
            sa.Column("security_changed_at", sa.DateTime(), nullable=True)
        )

    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("organization_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("user_security_version", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("revocation_reason", sa.String(length=100), nullable=True)
        )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE auth_sessions
               SET organization_id = (
                       SELECT users.organization_id
                         FROM users
                        WHERE users.id = auth_sessions.user_id
                   ),
                   user_security_version = COALESCE((
                       SELECT users.security_version
                         FROM users
                        WHERE users.id = auth_sessions.user_id
                   ), 1),
                   revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
                   revocation_reason = COALESCE(
                       revocation_reason,
                       'security_version_migration'
                   )
            """
        )
    )

    # Sessions without a valid tenant-bound user cannot be authenticated safely.
    connection.execute(
        sa.text(
            """
            DELETE FROM auth_sessions
             WHERE organization_id IS NULL
                OR user_security_version IS NULL
            """
        )
    )

    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.alter_column(
            "organization_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "user_security_version",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_auth_sessions_organization_id_organizations",
            "organizations",
            ["organization_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_auth_sessions_organization_id",
            ["organization_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.drop_index("ix_auth_sessions_organization_id")
        batch_op.drop_constraint(
            "fk_auth_sessions_organization_id_organizations",
            type_="foreignkey",
        )
        batch_op.drop_column("revocation_reason")
        batch_op.drop_column("user_security_version")
        batch_op.drop_column("organization_id")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("security_changed_at")
        batch_op.drop_column("security_version")
