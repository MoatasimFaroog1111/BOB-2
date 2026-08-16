"""Application orchestration for the persisted accounting classifier.

This service composes the existing accounting-intelligence service with the locked
persisted V2 classifier.  The persisted classifier is primary only for document/OCR
channels because that is the input distribution it was trained and evaluated on.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog
from app.ml.accounting_intelligence.odoo_learning_source import OdooAccountingLearningSource
from app.ml.accounting_intelligence.persisted_bundle import (
    PersistedAccountingPredictor,
    VerifiedAccountingBundleLoader,
)
from app.ml.accounting_intelligence.prediction_gate import AccountingPredictionGate
from app.services.accounting_intelligence import AccountingIntelligenceService
from app.services.tenant_erp_service import tenant_erp_resolver

PERSISTED_MODEL_CHANNELS = frozenset({"document", "ocr"})


class AccountingPersistedInferenceService:
    """Selects the correct read-only inference engine for each input channel."""

    def __init__(
        self,
        db: Session,
        *,
        persisted_predictor: PersistedAccountingPredictor | None = None,
        legacy_service: AccountingIntelligenceService | None = None,
        gate: AccountingPredictionGate | None = None,
    ) -> None:
        self.db = db
        self.persisted_predictor = persisted_predictor or PersistedAccountingPredictor()
        self.legacy_service = legacy_service or AccountingIntelligenceService(db)
        self.gate = gate or AccountingPredictionGate()

    def _catalog(
        self,
        *,
        organization_id: int,
        company_id: int | None,
    ) -> tuple[AccountingReferenceCatalog, bool, str | None]:
        try:
            _connection, erp = tenant_erp_resolver.resolve(self.db, organization_id)
            catalog = OdooAccountingLearningSource(erp).reference_catalog(company_id=company_id)
            return catalog, True, None
        except Exception as exc:
            return AccountingReferenceCatalog(), False, type(exc).__name__

    def status(self, *, organization_id: int) -> dict[str, Any]:
        base = self.legacy_service.status(organization_id=organization_id)
        bundle_status = self.persisted_predictor.loader.status()
        return {
            **base,
            "persisted_model": bundle_status,
            "document_inference_mode": (
                "verified_persisted_v2" if bundle_status.get("available") else "historical_semantic_fallback"
            ),
            "persisted_model_channels": sorted(PERSISTED_MODEL_CHANNELS),
            "auto_posting": False,
        }

    def predict(
        self,
        *,
        organization_id: int,
        text: str,
        channel: str,
        amount: float | None = None,
        move_type_hint: str | None = None,
        currency_hint: str | None = None,
        top_k: int = 12,
        company_id: int | None = None,
        documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # The existing semantic learner remains useful as fallback and for partner
        # resolution.  It has no ERP posting capability.
        historical = self.legacy_service.predict(
            organization_id=organization_id,
            text=text,
            amount=amount,
            move_type_hint=move_type_hint,
            currency_hint=currency_hint,
            top_k=top_k,
            company_id=company_id,
        )

        if channel not in PERSISTED_MODEL_CHANNELS:
            historical["primary_engine"] = "historical_semantic_structured"
            historical["persisted_model_skipped"] = {
                "reason": "channel_outside_attachment_training_contract",
                "eligible_channels": sorted(PERSISTED_MODEL_CHANNELS),
            }
            return historical

        catalog, catalog_live, catalog_error = self._catalog(
            organization_id=organization_id,
            company_id=company_id,
        )
        try:
            persisted = self.persisted_predictor.predict(
                text=text,
                catalog=catalog,
                documents=documents,
                top_k=min(max(int(top_k), 1), 10),
            )
            gate = self.gate.evaluate(persisted, amount=amount)
            return {
                "primary_engine": "verified_persisted_accounting_ml_v2",
                "persisted_model": persisted,
                "decision_gate": gate,
                "partner_candidates": historical.get("partners", []),
                "historical_semantic_support": {
                    "confidence": historical.get("confidence", 0.0),
                    "evidence_strength": historical.get("evidence_strength", 0.0),
                    "learning_examples_available": historical.get("learning_examples_available", 0),
                    "warnings": historical.get("warnings", []),
                },
                "live_erp_reference_catalog_available": catalog_live,
                "live_erp_reference_catalog_error": catalog_error,
                "company_scope": {"company_id": company_id, "applied": bool(company_id)},
                "audit_safe": {
                    "auto_posted_to_erp": False,
                    "approval_required": True,
                    "trained_during_request": False,
                    "test_data_used_during_request": False,
                },
            }
        except Exception as exc:
            # A missing/tampered/incompatible bundle must never break accounting
            # interpretation.  Fall back read-only and disclose the degraded mode.
            historical["primary_engine"] = "historical_semantic_structured_fallback"
            historical["persisted_model_unavailable"] = {
                "error_type": type(exc).__name__,
                "verified_bundle_required": True,
            }
            historical.setdefault("warnings", []).append(
                "The locked persisted accounting model was unavailable; read-only historical inference was used instead."
            )
            return historical
