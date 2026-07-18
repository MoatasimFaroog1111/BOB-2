"""add encrypted database secret versions

Revision ID: c6f1a8d4e920
Revises: b4e2c7d9f130
Create Date: 2026-07-16 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6f1a8d4e920"
down_revision: str | None = "b4e2c7d9f130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "encrypted_secret_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("secret_name", sa.String(length=127), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("authenticated_tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "key_version > 0",
            name="ck_encrypted_secret_versions_key_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('active','disabled')",
            name="ck_encrypted_secret_versions_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "secret_name",
            "version",
            name="uq_encrypted_secret_versions_name_version",
        ),
    )
    for column in ("secret_name", "version", "organization_id", "purpose"):
        op.create_index(
            f"ix_encrypted_secret_versions_{column}",
            "encrypted_secret_versions",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("purpose", "organization_id", "version", "secret_name"):
        op.drop_index(
            f"ix_encrypted_secret_versions_{column}",
            table_name="encrypted_secret_versions",
        )
    op.drop_table("encrypted_secret_versions")
