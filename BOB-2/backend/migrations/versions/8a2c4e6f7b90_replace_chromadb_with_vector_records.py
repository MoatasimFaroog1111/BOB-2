"""replace ChromaDB with tenant-isolated vector records

Revision ID: 8a2c4e6f7b90
Revises: 7f1a2b3c4d5e
Create Date: 2026-07-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8a2c4e6f7b90"
down_revision: Union[str, Sequence[str], None] = "7f1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vector_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("collection_name", sa.String(length=100), nullable=False),
        sa.Column("document_key", sa.String(length=128), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("record_metadata", sa.JSON(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "collection_name",
            "document_key",
            name="uq_vector_records_tenant_collection_key",
        ),
    )
    op.create_index("ix_vector_records_id", "vector_records", ["id"], unique=False)
    op.create_index(
        "ix_vector_records_organization_id",
        "vector_records",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_vector_records_collection_name",
        "vector_records",
        ["collection_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("vector_records")
