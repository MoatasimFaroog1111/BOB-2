"""Application service for persisted-ML -> safe Odoo draft creation.

The service always re-runs inference server-side, applies the deterministic gate,
builds a minimal proposal, and delegates ERP work to narrow adapters.  Preflight is
read-only; create_draft is the only mutation path and never posts entries.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.erp.accounting_draft_adapter import OdooAccountingDraftAdapter
from app.erp.accounting_draft_preflight import OdooAccountingDraftPreflight
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposalBuilder
from app.models.ai_accounting import AIDecisionAuditLog
from app.services.accounting_persisted_inference import AccountingPersistedInferenceService
from app.services.tenant_erp_service import tenant_erp_resolver


class AccountingMLDraftService:
    def __init__(
        self,
        db: Session,
        *,
        inference_service: AccountingPersistedInferenceService | None = None,
        proposal_builder: AccountingDraftProposalBuilder | None = None,
    ) -> None:
        self.db = db
        self.inference_service = inference_service or AccountingPersistedInferenceService(db)
        self.proposal_builder = proposal_builder or AccountingDraftProposalBuilder()

    def _audit(
        self,
        *,
        organization_id: int,
        proposal: dict[str, Any],
        result: dict[str, Any],
        confidence: float,
    ) -> bool:
        try:
            self.db.add(
                AIDecisionAuditLog(
                    organization_id=organization_id,
                    decision_type="accounting_ml_odoo_draft",
                    entity_type="account.move",
                    entity_id=None,
                    confidence_score=float(confidence),
                    explanation=(
                        "Verified persisted accounting ML v2 created or reused an Odoo draft only; "
                        "no posting action was executed."
                    ),
                    payload={
                        "proposal": proposal,
                        "odoo_result": result,
                        "auto_posted_to_erp": False,
                        "approval_required": True,
                    },
                )
            )
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False

    def _prepare(
        self,
        *,
        organization_id: int,
        text: str,
        channel: str,
        amount: Any,
        company_id: int,
        source_reference: str,
        entry_date: str,
        description: str | None,
        documents: list[dict[str, Any]] | None,
        top_k: int,
    ):
        inference = self.inference_service.predict(
            organization_id=organization_id,
            text=text,
            channel=channel,
            amount=float(amount),
            company_id=company_id,
            top_k=top_k,
            documents=documents,
        )
        if inference.get("primary_engine") != "verified_persisted_accounting_ml_v2":
            raise ValueError(
                "Verified persisted accounting ML v2 is required for automated draft creation."
            )

        persisted = dict(inference.get("persisted_model") or {})
        gate = dict(inference.get("decision_gate") or {})
        proposal = self.proposal_builder.build(
            prediction=persisted,
            decision_gate=gate,
            amount=amount,
            company_id=company_id,
            source_reference=source_reference,
            entry_date=entry_date,
            description=description,
            partner_candidates=list(inference.get("partner_candidates") or []),
        )

        connection, erp = tenant_erp_resolver.resolve(self.db, organization_id)
        provider_name = str(getattr(connection, "provider", "") or "").strip().lower()
        if provider_name != "odoo":
            raise ValueError("Persisted accounting ML draft creation currently supports Odoo only.")
        return persisted, proposal, erp

    def preflight(
        self,
        *,
        organization_id: int,
        text: str,
        channel: str,
        amount: Any,
        company_id: int,
        source_reference: str,
        entry_date: str,
        description: str | None = None,
        documents: list[dict[str, Any]] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        persisted, proposal, erp = self._prepare(
            organization_id=organization_id,
            text=text,
            channel=channel,
            amount=amount,
            company_id=company_id,
            source_reference=source_reference,
            entry_date=entry_date,
            description=description,
            documents=documents,
            top_k=top_k,
        )
        result = OdooAccountingDraftPreflight(erp).inspect(proposal)
        return {
            "status": "success",
            "primary_engine": "verified_persisted_accounting_ml_v2",
            "proposal": proposal.to_dict(),
            "live_odoo_preflight": result,
            "recommendations_not_auto_applied": proposal.recommendations,
            "safety": {
                "read_only": True,
                "erp_mutation_performed": False,
                "auto_posted_to_erp": False,
                "approval_required": True,
                "idempotency_ref": proposal.idempotency_ref,
                "confidence_proxy": float(persisted.get("confidence_proxy") or 0.0),
            },
        }

    def create_draft(
        self,
        *,
        organization_id: int,
        text: str,
        channel: str,
        amount: Any,
        company_id: int,
        source_reference: str,
        entry_date: str,
        description: str | None = None,
        documents: list[dict[str, Any]] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        persisted, proposal, erp = self._prepare(
            organization_id=organization_id,
            text=text,
            channel=channel,
            amount=amount,
            company_id=company_id,
            source_reference=source_reference,
            entry_date=entry_date,
            description=description,
            documents=documents,
            top_k=top_k,
        )

        # Re-run the exact read-only live preflight immediately before mutation so
        # stale/deprecated/cross-company references fail closed.
        preflight = OdooAccountingDraftPreflight(erp).inspect(proposal)
        adapter = OdooAccountingDraftAdapter(erp)
        write_result = adapter.create(proposal)
        proposal_payload = proposal.to_dict()
        confidence = float(persisted.get("confidence_proxy") or 0.0)
        audit_logged = self._audit(
            organization_id=organization_id,
            proposal=proposal_payload,
            result=write_result,
            confidence=confidence,
        )

        return {
            "status": "success",
            "primary_engine": "verified_persisted_accounting_ml_v2",
            "proposal": proposal_payload,
            "live_odoo_preflight": preflight,
            "odoo_draft": write_result,
            "audit_logged": audit_logged,
            "recommendations_not_auto_applied": proposal.recommendations,
            "safety": {
                "state_required": "draft",
                "auto_posted_to_erp": False,
                "posting_method_invoked": False,
                "approval_required": True,
                "tax_auto_applied": False,
                "analytic_auto_applied": False,
                "partner_auto_applied": False,
                "idempotency_ref": proposal.idempotency_ref,
            },
        }
