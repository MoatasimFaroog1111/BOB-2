from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class AIDocumentEmbedding(Base, TimestampMixin):
    __tablename__ = "ai_document_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    text_preview: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    classification: Mapped[dict] = mapped_column(JSON, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)


class AIDocumentMatch(Base, TimestampMixin):
    __tablename__ = "ai_document_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    source_embedding_id: Mapped[int] = mapped_column(ForeignKey("ai_document_embeddings.id"), nullable=False)
    target_embedding_id: Mapped[int | None] = mapped_column(ForeignKey("ai_document_embeddings.id"), nullable=True)
    match_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    match_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AIAccountingSuggestion(Base, TimestampMixin):
    __tablename__ = "ai_accounting_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    document_embedding_id: Mapped[int] = mapped_column(ForeignKey("ai_document_embeddings.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    debit_account: Mapped[dict] = mapped_column(JSON, nullable=False)
    credit_account: Mapped[dict] = mapped_column(JSON, nullable=False)
    vat_account: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    suggestion_payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class AIDecisionAuditLog(Base, TimestampMixin):
    __tablename__ = "ai_decision_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
