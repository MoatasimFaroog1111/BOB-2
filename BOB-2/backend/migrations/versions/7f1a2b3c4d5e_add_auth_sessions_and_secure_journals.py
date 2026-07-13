"""add revocable auth sessions and tenant-isolated journal entries

Revision ID: 7f1a2b3c4d5e
Revises: e2b5a8c9d104
Create Date: 2026-07-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7f1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "e2b5a8c9d104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("access_jti", sa.String(length=128), nullable=False),
        sa.Column("refresh_jti", sa.String(length=128), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_jti"),
        sa.UniqueConstraint("refresh_jti"),
    )
    op.create_index("ix_auth_sessions_family_id", "auth_sessions", ["family_id"], unique=False)
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)
    op.create_index("ix_auth_sessions_access_jti", "auth_sessions", ["access_jti"], unique=True)
    op.create_index("ix_auth_sessions_refresh_jti", "auth_sessions", ["refresh_jti"], unique=True)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False)
    op.create_index("ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"], unique=False)

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("total_debit", sa.Float(), nullable=False),
        sa.Column("total_credit", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_entries_id", "journal_entries", ["id"], unique=False)
    op.create_index("ix_journal_entries_organization_id", "journal_entries", ["organization_id"], unique=False)
    op.create_index("ix_journal_entries_created_by_user_id", "journal_entries", ["created_by_user_id"], unique=False)
    op.create_index("ix_journal_entries_entry_date", "journal_entries", ["entry_date"], unique=False)
    op.create_index("ix_journal_entries_reference", "journal_entries", ["reference"], unique=False)
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"], unique=False)

    # Neutralize any account created by the previously published default credentials.
    # Administrators may reactivate it only after setting a new secret out of band.
    op.execute(
        sa.text("UPDATE users SET is_active = false WHERE email = 'owner@guardian.local'")
    )


def downgrade() -> None:
    op.drop_table("journal_entries")
    op.drop_table("auth_sessions")
