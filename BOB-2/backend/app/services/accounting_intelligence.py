"""Application service for ERP-grounded accounting learning and inference."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog
from app.ml.accounting_intelligence.feature_engineering import structured_features
from app.ml.accounting_intelligence.hybrid_learner import (
    HybridAccountingLearner,
    RetrievedLearningExample,
)
from app.ml.accounting_intelligence.odoo_learning_source import OdooAccountingLearningSource
from app.models.ai_accounting import AIDecisionAuditLog, AIDocumentEmbedding
from app.services.accounting_ai import EmbeddingProvider
from app.services.tenant_erp_service import tenant_erp_resolver

LEARNING_SOURCE_TYPE = "erp_historical_entry"


class AccountingIntelligenceService:
    """Coordinates learning without owning ERP credentials or posting methods."""

    def __init__(
        self,
        db: Session,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        learner: HybridAccountingLearner | None = None,
    ):
        self.db = db
        self.embedding_provider = embedding_provider or EmbeddingProvider()
        self.learner = learner or HybridAccountingLearner()

    def _source_and_catalog(self, organization_id: int):
        _connection, erp = tenant_erp_resolver.resolve(self.db, organization_id)
        source = OdooAccountingLearningSource(erp)
        return source, source.reference_catalog()

    @staticmethod
    def _classification_payload(example) -> dict[str, Any]:
        return {
            "document_type": "erp_historical_entry",
            "confidence_score": 1.0,
            "learning_features": structured_features(example),
            "outputs": {
                "move_type": example.move_type,
                "journal_id": example.journal_id,
                "partner_id": example.partner_id,
                "debit_account_ids": list(example.debit_account_ids),
                "credit_account_ids": list(example.credit_account_ids),
                "tax_ids": list(example.tax_ids),
                "analytic_account_ids": list(example.analytic_account_ids),
            },
            "source": {
                "source_id": example.source_id,
                "occurred_on": example.occurred_on,
                "amount": example.amount,
                "currency": example.currency,
                "attachment_count": len(example.attachment_features),
                "feature_metadata": example.feature_metadata,
            },
        }

    def sync_historical_learning(
        self,
        *,
        organization_id: int,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 1000,
        company_id: int | None = None,
    ) -> dict[str, Any]:
        source, catalog = self._source_and_catalog(organization_id)
        examples = source.historical_examples(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            company_id=company_id,
        )

        created = 0
        updated = 0
        unchanged = 0
        indexed = 0
        for example in examples:
            text_hash = hashlib.sha256(example.text.encode("utf-8")).hexdigest()
            existing = (
                self.db.query(AIDocumentEmbedding)
                .filter(
                    AIDocumentEmbedding.organization_id == organization_id,
                    AIDocumentEmbedding.source_type == LEARNING_SOURCE_TYPE,
                    AIDocumentEmbedding.source_reference == example.source_reference,
                )
                .first()
            )
            classification = self._classification_payload(example)
            if existing and existing.text_hash == text_hash and existing.classification == classification:
                unchanged += 1
                continue

            vector, model_name = self.embedding_provider.embed(example.text)
            if existing:
                row = existing
                row.text_hash = text_hash
                row.text_preview = example.text[:2000]
                row.embedding_model = model_name
                row.embedding_dimension = len(vector)
                row.embedding_vector = vector
                row.classification = classification
                row.confidence_score = 1.0
                updated += 1
            else:
                row = AIDocumentEmbedding(
                    organization_id=organization_id,
                    document_id=None,
                    source_type=LEARNING_SOURCE_TYPE,
                    source_reference=example.source_reference,
                    text_hash=text_hash,
                    text_preview=example.text[:2000],
                    embedding_model=model_name,
                    embedding_dimension=len(vector),
                    embedding_vector=vector,
                    classification=classification,
                    confidence_score=1.0,
                )
                self.db.add(row)
                self.db.flush()
                created += 1

            try:
                from app.services.vector_db import index_accounting_embedding

                index_accounting_embedding(
                    text=example.text,
                    embedding_id=row.id,
                    metadata={
                        "source_type": LEARNING_SOURCE_TYPE,
                        "source_reference": example.source_reference,
                        "move_type": example.move_type or "",
                    },
                    org_id=organization_id,
                    vector=vector,
                )
                indexed += 1
            except Exception:
                # SQL remains the durable source of truth if the vector accelerator is unavailable.
                pass

        self.db.add(
            AIDecisionAuditLog(
                organization_id=organization_id,
                decision_type="erp_learning_sync",
                entity_type="accounting_intelligence",
                entity_id=None,
                confidence_score=1.0,
                explanation="Read-only ERP accounting history synchronized as learning examples; no ERP mutation occurred.",
                payload={
                    "requested_limit": limit,
                    "examples_read": len(examples),
                    "created": created,
                    "updated": updated,
                    "unchanged": unchanged,
                    "vector_indexed": indexed,
                    "date_from": date_from,
                    "date_to": date_to,
                    "company_id": company_id,
                    "reference_catalog": self._catalog_counts(catalog),
                    "auto_posted_to_erp": False,
                },
            )
        )
        self.db.commit()
        return {
            "status": "success",
            "examples_read": len(examples),
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "vector_indexed": indexed,
            "reference_catalog": self._catalog_counts(catalog),
            "safety": {
                "erp_mutation": False,
                "training_source": "posted historical accounting entries",
                "raw_attachment_binaries_read": False,
                "attachment_metadata_used_as_features": True,
            },
        }

    @staticmethod
    def _catalog_counts(catalog: AccountingReferenceCatalog) -> dict[str, int]:
        return {
            "accounts": len(catalog.accounts),
            "journals": len(catalog.journals),
            "taxes": len(catalog.taxes),
            "partners": len(catalog.partners),
            "analytic_accounts": len(catalog.analytic_accounts),
            "products": len(catalog.products),
        }

    def _learning_examples(self, organization_id: int, limit: int = 1500) -> list[RetrievedLearningExample]:
        rows = (
            self.db.query(AIDocumentEmbedding)
            .filter(
                AIDocumentEmbedding.organization_id == organization_id,
                AIDocumentEmbedding.source_type == LEARNING_SOURCE_TYPE,
            )
            .order_by(AIDocumentEmbedding.created_at.desc())
            .limit(min(max(limit, 1), 5000))
            .all()
        )
        result: list[RetrievedLearningExample] = []
        for row in rows:
            classification = row.classification or {}
            outputs = classification.get("outputs") or {}
            features = classification.get("learning_features") or {}
            if not row.embedding_vector or not outputs:
                continue
            result.append(
                RetrievedLearningExample(
                    source_reference=row.source_reference or f"embedding:{row.id}",
                    text_preview=row.text_preview or "",
                    vector=[float(value) for value in row.embedding_vector],
                    outputs=dict(outputs),
                    features=dict(features),
                )
            )
        return result

    def predict(
        self,
        *,
        organization_id: int,
        text: str,
        amount: float | None = None,
        move_type_hint: str | None = None,
        currency_hint: str | None = None,
        top_k: int = 12,
    ) -> dict[str, Any]:
        clean_text = text.strip()
        if len(clean_text) < 4:
            raise ValueError("Accounting intelligence input is too short.")

        catalog_live = True
        catalog_error_type: str | None = None
        try:
            _source, catalog = self._source_and_catalog(organization_id)
        except Exception as exc:
            # Learned memory remains usable when the ERP is temporarily unavailable.
            # IDs are returned without pretending that live names/codes were validated.
            catalog = AccountingReferenceCatalog()
            catalog_live = False
            catalog_error_type = type(exc).__name__

        examples = self._learning_examples(organization_id)
        vector, model_name = self.embedding_provider.embed(clean_text)
        prediction = self.learner.predict(
            query_text=clean_text,
            query_vector=vector,
            amount=amount,
            move_type_hint=move_type_hint,
            currency_hint=currency_hint,
            catalog=catalog,
            examples=examples,
            top_k=top_k,
        )
        prediction["embedding_model"] = model_name
        prediction["learning_examples_available"] = len(examples)
        prediction["reference_catalog"] = self._catalog_counts(catalog)
        prediction["live_erp_reference_catalog_available"] = catalog_live
        if not catalog_live:
            finding = {
                "code": "LIVE_ERP_REFERENCE_CATALOG_UNAVAILABLE",
                "severity": "medium",
                "message": "Learned IDs are available from BOB memory, but live ERP names/codes could not be revalidated.",
                "evidence": {"error_type": catalog_error_type},
            }
            prediction.setdefault("audit_findings", []).append(finding)
            prediction.setdefault("warnings", []).append(finding["message"])
        return prediction

    def status(self, *, organization_id: int) -> dict[str, Any]:
        learned = (
            self.db.query(AIDocumentEmbedding)
            .filter(
                AIDocumentEmbedding.organization_id == organization_id,
                AIDocumentEmbedding.source_type == LEARNING_SOURCE_TYPE,
            )
            .count()
        )
        latest = (
            self.db.query(AIDocumentEmbedding)
            .filter(
                AIDocumentEmbedding.organization_id == organization_id,
                AIDocumentEmbedding.source_type == LEARNING_SOURCE_TYPE,
            )
            .order_by(AIDocumentEmbedding.created_at.desc())
            .first()
        )
        return {
            "status": "success",
            "learning_examples": learned,
            "latest_learning_example_at": latest.created_at.isoformat() if latest else None,
            "mode": "hybrid_deep_semantic_structured_learning",
            "auto_posting": False,
        }
