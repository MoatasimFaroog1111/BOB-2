"""add accounting ai matching tables

Revision ID: 9b7c1e4a2d31
Revises: c8dfd29f9d10
Create Date: 2026-06-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9b7c1e4a2d31"
down_revision: Union[str, Sequence[str], None] = "c8dfd29f9d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("ai_document_embeddings", sa.Column("id", sa.Integer(), nullable=False), sa.Column("organization_id", sa.Integer(), nullable=False), sa.Column("document_id", sa.Integer(), nullable=True), sa.Column("source_type", sa.String(length=100), nullable=False), sa.Column("source_reference", sa.String(length=500), nullable=True), sa.Column("text_hash", sa.String(length=64), nullable=False), sa.Column("text_preview", sa.Text(), nullable=False), sa.Column("embedding_model", sa.String(length=255), nullable=False), sa.Column("embedding_dimension", sa.Integer(), nullable=False), sa.Column("embedding_vector", sa.JSON(), nullable=False), sa.Column("classification", sa.JSON(), nullable=False), sa.Column("confidence_score", sa.Float(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["document_id"], ["documents.id"]), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_ai_document_embeddings_id"), "ai_document_embeddings", ["id"], unique=False)
    op.create_index(op.f("ix_ai_document_embeddings_organization_id"), "ai_document_embeddings", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ai_document_embeddings_document_id"), "ai_document_embeddings", ["document_id"], unique=False)
    op.create_index(op.f("ix_ai_document_embeddings_source_type"), "ai_document_embeddings", ["source_type"], unique=False)
    op.create_index(op.f("ix_ai_document_embeddings_text_hash"), "ai_document_embeddings", ["text_hash"], unique=False)
    op.create_table("ai_document_matches", sa.Column("id", sa.Integer(), nullable=False), sa.Column("organization_id", sa.Integer(), nullable=False), sa.Column("source_embedding_id", sa.Integer(), nullable=False), sa.Column("target_embedding_id", sa.Integer(), nullable=True), sa.Column("match_type", sa.String(length=100), nullable=False), sa.Column("confidence_score", sa.Float(), nullable=False), sa.Column("similarity_score", sa.Float(), nullable=False), sa.Column("explanation", sa.Text(), nullable=False), sa.Column("status", sa.String(length=50), nullable=False), sa.Column("match_metadata", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]), sa.ForeignKeyConstraint(["source_embedding_id"], ["ai_document_embeddings.id"]), sa.ForeignKeyConstraint(["target_embedding_id"], ["ai_document_embeddings.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_ai_document_matches_id"), "ai_document_matches", ["id"], unique=False)
    op.create_index(op.f("ix_ai_document_matches_organization_id"), "ai_document_matches", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ai_document_matches_match_type"), "ai_document_matches", ["match_type"], unique=False)
    op.create_index(op.f("ix_ai_document_matches_status"), "ai_document_matches", ["status"], unique=False)
    op.create_table("ai_accounting_suggestions", sa.Column("id", sa.Integer(), nullable=False), sa.Column("organization_id", sa.Integer(), nullable=False), sa.Column("document_embedding_id", sa.Integer(), nullable=False), sa.Column("status", sa.String(length=50), nullable=False), sa.Column("confidence_score", sa.Float(), nullable=False), sa.Column("explanation", sa.Text(), nullable=False), sa.Column("debit_account", sa.JSON(), nullable=False), sa.Column("credit_account", sa.JSON(), nullable=False), sa.Column("vat_account", sa.JSON(), nullable=True), sa.Column("suggestion_payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["document_embedding_id"], ["ai_document_embeddings.id"]), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_ai_accounting_suggestions_id"), "ai_accounting_suggestions", ["id"], unique=False)
    op.create_index(op.f("ix_ai_accounting_suggestions_organization_id"), "ai_accounting_suggestions", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ai_accounting_suggestions_status"), "ai_accounting_suggestions", ["status"], unique=False)
    op.create_table("ai_decision_audit_log", sa.Column("id", sa.Integer(), nullable=False), sa.Column("organization_id", sa.Integer(), nullable=False), sa.Column("decision_type", sa.String(length=100), nullable=False), sa.Column("entity_type", sa.String(length=100), nullable=False), sa.Column("entity_id", sa.String(length=100), nullable=True), sa.Column("confidence_score", sa.Float(), nullable=False), sa.Column("explanation", sa.Text(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_ai_decision_audit_log_id"), "ai_decision_audit_log", ["id"], unique=False)
    op.create_index(op.f("ix_ai_decision_audit_log_organization_id"), "ai_decision_audit_log", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ai_decision_audit_log_decision_type"), "ai_decision_audit_log", ["decision_type"], unique=False)


def downgrade() -> None:
    op.drop_table("ai_decision_audit_log")
    op.drop_table("ai_accounting_suggestions")
    op.drop_table("ai_document_matches")
    op.drop_table("ai_document_embeddings")
