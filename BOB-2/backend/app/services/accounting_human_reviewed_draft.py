"""Human-reviewed accounting draft orchestration.

This service is the explicit review path used when a human accountant approves or
corrects persisted V2 recommendations. It never changes model thresholds and never
posts. The original deterministic gate is retained in the audit payload; reviewer
choices are resolved again against the live Odoo catalog and preflighted before the
narrow draft/attachment adapters are allowed to mutate Odoo.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.erp.accounting_draft_adapter import OdooAccountingDraftAdapter
from app.erp.accounting_draft_attachment_adapter import (
    AccountingDraftAttachmentError,
    OdooAccountingDraftAttachmentAdapter,
)
from app.erp.accounting_draft_preflight import OdooAccountingDraftPreflight
from app.ml.accounting_intelligence.draft_proposal import (
    AccountingDraftProposalBuilder,
    AccountingDraftProposalError,
)
from app.ml.accounting_intelligence.odoo_learning_source import OdooAccountingLearningSource
from app.models.ai_accounting import AIDecisionAuditLog
from app.services.accounting_document_review import AccountingDocumentReviewService
from app.services.tenant_erp_service import tenant_erp_resolver


class AccountingHumanReviewedDraftService:
    """Create/reuse one reviewed Odoo draft and attach its validated source file."""

    def __init__(
        self,
        db: Session,
        *,
        document_review: AccountingDocumentReviewService | None = None,
        proposal_builder: AccountingDraftProposalBuilder | None = None,
    ) -> None:
        self.db = db
        self.document_review = document_review or AccountingDocumentReviewService(db)
        self.proposal_builder = proposal_builder or AccountingDraftProposalBuilder()

    @staticmethod
    def _catalog_map(rows: tuple[dict[str, Any], ...]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            try:
                result[int(row["id"])] = dict(row)
            except (KeyError, TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _required_live(
        mapping: dict[int, dict[str, Any]],
        record_id: int,
        *,
        code: str,
    ) -> dict[str, Any]:
        try:
            identifier = int(record_id)
        except (TypeError, ValueError) as exc:
            raise AccountingDraftProposalError(
                f"{code}_ID_INVALID",
                f"Reviewed {code.lower().replace('_', ' ')} ID is invalid.",
            ) from exc
        row = mapping.get(identifier)
        if not row:
            raise AccountingDraftProposalError(
                f"{code}_NOT_IN_LIVE_CATALOG",
                f"Reviewed {code.lower().replace('_', ' ')} is not available in the selected live Odoo company.",
            )
        return dict(row)

    @staticmethod
    def _selected_tax_requires_review(persisted: dict[str, Any]) -> bool:
        return any(bool(row.get("selected")) for row in (persisted.get("taxes") or []))

    @staticmethod
    def _review_enrichment(
        *,
        debit_partner_id: int | None,
        credit_partner_id: int | None,
        debit_analytic_id: int | None,
        credit_analytic_id: int | None,
    ) -> dict[str, Any]:
        auto_applied: list[str] = []
        reviewed_applied: list[str] = []
        if debit_partner_id or credit_partner_id:
            reviewed_applied.append("partner")
        if debit_analytic_id or credit_analytic_id:
            reviewed_applied.append("analytic_distribution")
        return {
            "debit_partner_id": int(debit_partner_id) if debit_partner_id else None,
            "credit_partner_id": int(credit_partner_id) if credit_partner_id else None,
            "debit_analytic_distribution": (
                {str(int(debit_analytic_id)): 100.0} if debit_analytic_id else {}
            ),
            "credit_analytic_distribution": (
                {str(int(credit_analytic_id)): 100.0} if credit_analytic_id else {}
            ),
            "auto_applied": auto_applied,
            "human_reviewed_applied": reviewed_applied,
            "not_auto_applied": ["tax"],
            "review_mode": "explicit_human_approval",
        }

    def _audit(
        self,
        *,
        organization_id: int,
        move_id: int | None,
        confidence: float,
        payload: dict[str, Any],
    ) -> bool:
        try:
            self.db.add(
                AIDecisionAuditLog(
                    organization_id=organization_id,
                    decision_type="accounting_human_reviewed_odoo_draft",
                    entity_type="account.move",
                    entity_id=move_id,
                    confidence_score=float(confidence),
                    explanation=(
                        "A human reviewer explicitly approved/corrected persisted accounting ML V2 "
                        "recommendations. Live Odoo references were preflighted, the source document "
                        "was attached when possible, and no posting action was executed."
                    ),
                    payload=payload,
                )
            )
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False

    def create(
        self,
        *,
        organization_id: int,
        company_id: int,
        filename: str,
        mimetype: str,
        content: bytes,
        amount: Any,
        entry_date: str,
        description: str | None,
        journal_id: int,
        debit_account_id: int,
        credit_account_id: int,
        debit_partner_id: int | None = None,
        credit_partner_id: int | None = None,
        debit_analytic_id: int | None = None,
        credit_analytic_id: int | None = None,
        reviewer: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        analysis = self.document_review.analyze(
            organization_id=organization_id,
            company_id=company_id,
            filename=filename,
            mimetype=mimetype,
            content=content,
            amount_override=float(amount),
        )
        persisted = dict(analysis.get("prediction") or {})
        original_gate = dict(analysis.get("decision_gate") or {})

        if self._selected_tax_requires_review(persisted):
            raise AccountingDraftProposalError(
                "TAX_REVIEW_UI_REQUIRED",
                "The model selected a tax label. Tax-bearing documents require the dedicated tax review workflow before draft creation.",
            )

        connection, erp = tenant_erp_resolver.resolve(self.db, organization_id)
        provider_name = str(getattr(connection, "provider", "") or "").strip().lower()
        if provider_name != "odoo":
            raise ValueError("Human-reviewed accounting draft creation currently supports Odoo only.")

        catalog = OdooAccountingLearningSource(erp).reference_catalog(company_id=company_id)
        account_map = self._catalog_map(catalog.accounts)
        journal_map = self._catalog_map(catalog.journals)
        partner_map = self._catalog_map(catalog.partners)
        analytic_map = self._catalog_map(catalog.analytic_accounts)

        journal = self._required_live(journal_map, journal_id, code="JOURNAL")
        debit = self._required_live(account_map, debit_account_id, code="DEBIT_ACCOUNT")
        credit = self._required_live(account_map, credit_account_id, code="CREDIT_ACCOUNT")
        if int(debit_account_id) == int(credit_account_id):
            raise AccountingDraftProposalError(
                "CONTRADICTORY_ACCOUNT_SIDES",
                "Reviewed debit and credit accounts cannot be identical.",
            )

        for partner_id, side in ((debit_partner_id, "DEBIT"), (credit_partner_id, "CREDIT")):
            if partner_id:
                self._required_live(partner_map, int(partner_id), code=f"{side}_PARTNER")
        for analytic_id, side in ((debit_analytic_id, "DEBIT"), (credit_analytic_id, "CREDIT")):
            if analytic_id:
                self._required_live(analytic_map, int(analytic_id), code=f"{side}_ANALYTIC")

        review_prediction = dict(persisted)
        review_prediction["move_type"] = [{
            "label": "entry",
            "selected": True,
            "model_score": next(
                (
                    float(row.get("model_score") or 0.0)
                    for row in (persisted.get("move_type") or [])
                    if row.get("label") == "entry"
                ),
                0.0,
            ),
            "live_reference_resolved": False,
        }]
        review_prediction["journals"] = [{
            **journal,
            "label": str(journal.get("code") or journal.get("name") or journal_id),
            "selected": True,
            "live_reference_resolved": True,
        }]
        review_prediction["debit_accounts"] = [{
            **debit,
            "label": str(debit.get("code") or debit_account_id),
            "selected": True,
            "live_reference_resolved": True,
        }]
        review_prediction["credit_accounts"] = [{
            **credit,
            "label": str(credit.get("code") or credit_account_id),
            "selected": True,
            "live_reference_resolved": True,
        }]
        review_prediction["taxes"] = []

        enrichment = self._review_enrichment(
            debit_partner_id=debit_partner_id,
            credit_partner_id=credit_partner_id,
            debit_analytic_id=debit_analytic_id,
            credit_analytic_id=credit_analytic_id,
        )
        enrichment["original_decision_gate"] = original_gate
        enrichment["reviewer"] = dict(reviewer or {})
        enrichment["source_sha256"] = analysis["source"]["sha256"]

        review_gate = {
            "draft_eligible": True,
            "review_required": True,
            "auto_post_allowed": False,
            "human_review_override": True,
            "original_gate": original_gate,
        }
        proposal = self.proposal_builder.build(
            prediction=review_prediction,
            decision_gate=review_gate,
            amount=amount,
            company_id=company_id,
            source_reference=str(analysis["source"]["source_reference"]),
            entry_date=entry_date,
            description=description or filename,
            partner_candidates=list(analysis.get("partner_candidates") or []),
            enrichment=enrichment,
        )

        preflight = OdooAccountingDraftPreflight(erp).inspect(proposal)
        write_result = OdooAccountingDraftAdapter(erp).create(proposal)

        attachment_result: dict[str, Any] | None = None
        attachment_error: dict[str, Any] | None = None
        try:
            attachment_result = OdooAccountingDraftAttachmentAdapter(erp).attach(
                move_id=int(write_result["move_id"]),
                filename=filename,
                mimetype=mimetype,
                content=content,
            )
        except AccountingDraftAttachmentError as exc:
            # Never delete an accounting draft as compensation. The draft stays
            # unposted and the attachment operation remains safely retryable.
            attachment_error = {"code": exc.code, "message": str(exc)}

        proposal_payload = proposal.to_dict()
        audit_payload = {
            "review_mode": "explicit_human_approval",
            "reviewer": dict(reviewer or {}),
            "source": {
                "filename": analysis["source"]["filename"],
                "mimetype": analysis["source"]["mimetype"],
                "size_bytes": analysis["source"]["size_bytes"],
                "sha256": analysis["source"]["sha256"],
                "source_reference": analysis["source"]["source_reference"],
            },
            "original_decision_gate": original_gate,
            "reviewed_selection": {
                "journal_id": int(journal_id),
                "debit_account_id": int(debit_account_id),
                "credit_account_id": int(credit_account_id),
                "debit_partner_id": int(debit_partner_id) if debit_partner_id else None,
                "credit_partner_id": int(credit_partner_id) if credit_partner_id else None,
                "debit_analytic_id": int(debit_analytic_id) if debit_analytic_id else None,
                "credit_analytic_id": int(credit_analytic_id) if credit_analytic_id else None,
                "amount": str(amount),
                "entry_date": str(entry_date),
            },
            "proposal": proposal_payload,
            "odoo_draft": write_result,
            "attachment": attachment_result,
            "attachment_error": attachment_error,
            "model_thresholds_changed": False,
            "auto_posted_to_erp": False,
            "posting_method_invoked": False,
        }
        audit_logged = self._audit(
            organization_id=organization_id,
            move_id=int(write_result["move_id"]),
            confidence=float(persisted.get("confidence_proxy") or 0.0),
            payload=audit_payload,
        )

        return {
            "status": "partial_success" if attachment_error else "success",
            "primary_engine": "verified_persisted_accounting_ml_v2",
            "original_decision_gate": original_gate,
            "human_review_override": True,
            "proposal": proposal_payload,
            "live_odoo_preflight": preflight,
            "odoo_draft": write_result,
            "attachment": attachment_result,
            "attachment_error": attachment_error,
            "audit_logged": audit_logged,
            "safety": {
                "state_required": "draft",
                "human_approval_recorded": True,
                "model_thresholds_changed": False,
                "auto_posted_to_erp": False,
                "posting_method_invoked": False,
                "tax_auto_applied": False,
                "source_attachment_requested": True,
                "source_attachment_attached": attachment_result is not None,
                "idempotency_ref": proposal.idempotency_ref,
            },
        }
