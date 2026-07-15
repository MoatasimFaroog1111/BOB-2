"""add tenant-scoped remote secret metadata

Revision ID: 9c7f2a4b1d80
Revises: 7a4c9e2d1f60
Create Date: 2026-07-15 08:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c7f2a4b1d80"
down_revision: str | None = "7a4c9e2d1f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_secret_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("secret_name", sa.String(length=127), nullable=False),
        sa.Column("current_version", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rotated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("last_rotated_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','revoked')",
            name="ck_tenant_secret_bindings_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["rotated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "purpose",
            name="uq_tenant_secret_bindings_organization_purpose",
        ),
    )
    op.create_index(op.f("ix_tenant_secret_bindings_id"), "tenant_secret_bindings", ["id"])
    op.create_index(
        op.f("ix_tenant_secret_bindings_organization_id"),
        "tenant_secret_bindings",
        ["organization_id"],
    )
    op.create_index(op.f("ix_tenant_secret_bindings_purpose"), "tenant_secret_bindings", ["purpose"])
    op.create_index(op.f("ix_tenant_secret_bindings_status"), "tenant_secret_bindings", ["status"])
    op.create_index(
        op.f("ix_tenant_secret_bindings_created_by_user_id"),
        "tenant_secret_bindings",
        ["created_by_user_id"],
    )
    op.create_index(
        op.f("ix_tenant_secret_bindings_rotated_by_user_id"),
        "tenant_secret_bindings",
        ["rotated_by_user_id"],
    )
    op.create_index(
        op.f("ix_tenant_secret_bindings_revoked_by_user_id"),
        "tenant_secret_bindings",
        ["revoked_by_user_id"],
    )

    op.create_table(
        "tenant_secret_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("binding_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("secret_name", sa.String(length=127), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','superseded','revoked')",
            name="ck_tenant_secret_versions_status",
        ),
        sa.ForeignKeyConstraint(["binding_id"], ["tenant_secret_bindings.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "secret_name",
            "version",
            name="uq_tenant_secret_versions_remote_version",
        ),
    )
    op.create_index(op.f("ix_tenant_secret_versions_id"), "tenant_secret_versions", ["id"])
    op.create_index(op.f("ix_tenant_secret_versions_binding_id"), "tenant_secret_versions", ["binding_id"])
    op.create_index(
        op.f("ix_tenant_secret_versions_organization_id"),
        "tenant_secret_versions",
        ["organization_id"],
    )
    op.create_index(op.f("ix_tenant_secret_versions_purpose"), "tenant_secret_versions", ["purpose"])
    op.create_index(op.f("ix_tenant_secret_versions_status"), "tenant_secret_versions", ["status"])
    op.create_index(
        op.f("ix_tenant_secret_versions_created_by_user_id"),
        "tenant_secret_versions",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_secret_versions_created_by_user_id"), table_name="tenant_secret_versions")
    op.drop_index(op.f("ix_tenant_secret_versions_status"), table_name="tenant_secret_versions")
    op.drop_index(op.f("ix_tenant_secret_versions_purpose"), table_name="tenant_secret_versions")
    op.drop_index(op.f("ix_tenant_secret_versions_organization_id"), table_name="tenant_secret_versions")
    op.drop_index(op.f("ix_tenant_secret_versions_binding_id"), table_name="tenant_secret_versions")
    op.drop_index(op.f("ix_tenant_secret_versions_id"), table_name="tenant_secret_versions")
    op.drop_table("tenant_secret_versions")

    op.drop_index(op.f("ix_tenant_secret_bindings_revoked_by_user_id"), table_name="tenant_secret_bindings")
    op.drop_index(op.f("ix_tenant_secret_bindings_rotated_by_user_id"), table_name="tenant_secret_bindings")
    op.drop_index(op.f("ix_tenant_secret_bindings_created_by_user_id"), table_name="tenant_secret_bindings")
    op.drop_index(op.f("ix_tenant_secret_bindings_status"), table_name="tenant_secret_bindings")
    op.drop_index(op.f("ix_tenant_secret_bindings_purpose"), table_name="tenant_secret_bindings")
    op.drop_index(op.f("ix_tenant_secret_bindings_organization_id"), table_name="tenant_secret_bindings")
    op.drop_index(op.f("ix_tenant_secret_bindings_id"), table_name="tenant_secret_bindings")
    op.drop_table("tenant_secret_bindings")
