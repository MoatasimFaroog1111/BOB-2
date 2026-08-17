"""Document -> persisted accounting ML review analysis.

This service owns no ERP mutation. It accepts already validated document bytes,
extracts accounting text/fields with the existing document AI, runs the locked
persisted V2 inference path, and returns a compact review payload for a human
accountant. Source binaries are never persisted here.
"""

from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.erp.document_ai import GuardianDocumentAI
from app.ml.accounting_intelligence.draft_enrichment import AccountingDraftEnrichmentPolicy
from app.security.file_validation import sanitize_filename
from app.services.accounting_persisted_inference import AccountingPersistedInferenceService


class AccountingDocumentReviewService:
    """Read-only uploaded-document accounting review analysis."""

    _FIELD_EXTRACTORS = {
        "receipt": "extract_receipt_fields",
        "sadad_receipt": "extract_receipt_fields",
        "invoice": "extract_invoice_fields",
        "zatca_invoice": "extract_invoice_fields",
        "vendor_bill": "extract_invoice_fields",
        "payment_voucher": "extract_payment_voucher_fields",
        "purchase_order": "extract_purchase_order_fields",
        "bank_statement": "extract_bank_statement_fields",
    }

    def __init__(
        self,
        db: Session,
        *,
        document_ai: GuardianDocumentAI | None = None,
        inference_service: AccountingPersistedInferenceService | None = None,
        enrichment_policy: AccountingDraftEnrichmentPolicy | None = None,
    ) -> None:
        self.db = db
        self.document_ai = document_ai or GuardianDocumentAI()
        self.inference_service = inference_service or AccountingPersistedInferenceService(db)
        self.enrichment_policy = enrichment_policy or AccountingDraftEnrichmentPolicy()

    @staticmethod
    def _normalize_date(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _selected_id(rows: list[dict[str, Any]]) -> int | None:
        selected = [row for row in rows if row.get("selected") and row.get("id")]
        if len(selected) != 1:
            return None
        try:
            return int(selected[0]["id"])
        except (TypeError, ValueError):
            return None

    def _fields(self, raw_text: str, *, filename: str) -> tuple[str, dict[str, Any], list[str]]:
        document_class = self.document_ai.detect_document_class(raw_text, file_path=filename)
        extractor_name = self._FIELD_EXTRACTORS.get(document_class)
        if extractor_name:
            fields = dict(getattr(self.document_ai, extractor_name)(raw_text) or {})
            fields["document_class"] = document_class
        else:
            fields = {
                "document_class": document_class,
                "supplier_name": self.document_ai.detect_supplier_name(raw_text),
                "total_amount": None,
                "currency": "SAR",
            }

        warnings: list[str] = []
        if raw_text.startswith("OCR_ERROR:"):
            warnings.append("ocr_engine_missing_or_failed")
        if fields.get("total_amount") is None and fields.get("amount") is None:
            warnings.append("total_amount_not_detected")
        return document_class, fields, warnings

    def analyze(
        self,
        *,
        organization_id: int,
        company_id: int,
        filename: str,
        mimetype: str,
        content: bytes,
        amount_override: float | None = None,
    ) -> dict[str, Any]:
        if int(company_id) <= 0:
            raise ValueError("A positive company_id is required for accounting review.")
        if not content:
            raise ValueError("Source document bytes are required for accounting review.")

        safe_name = sanitize_filename(filename or "source-document")
        suffix = Path(safe_name).suffix.lower() or ".bin"
        sha256 = hashlib.sha256(content).hexdigest()

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="bob-accounting-review-", suffix=suffix, delete=False) as handle:
                handle.write(content)
                temp_path = Path(handle.name)

            raw_text = str(self.document_ai.extract_text(str(temp_path)) or "").strip()
            if len(raw_text) < 4 or raw_text.startswith("OCR_ERROR:"):
                raise ValueError("The uploaded document did not yield usable accounting text.")

            document_class, fields, warnings = self._fields(raw_text, filename=safe_name)
            detected_amount = fields.get("total_amount")
            if detected_amount is None:
                detected_amount = fields.get("amount")
            amount = float(amount_override) if amount_override is not None else (
                float(detected_amount) if detected_amount is not None else None
            )

            date_value = (
                fields.get("processing_date")
                or fields.get("payment_date")
                or fields.get("invoice_date")
            )
            entry_date = self._normalize_date(date_value)
            currency = str(fields.get("currency") or fields.get("currency_guess") or "SAR")

            extractor = "pdf_text" if suffix == ".pdf" else "image_ocr"
            documents = [{
                "extension": suffix,
                "mime": mimetype or "application/octet-stream",
                "extractor": extractor,
                "ocr_pages": 0,
            }]
            inference = self.inference_service.predict(
                organization_id=organization_id,
                text=raw_text,
                channel="document",
                amount=amount,
                currency_hint=currency,
                company_id=company_id,
                top_k=10,
                documents=documents,
            )
            if inference.get("primary_engine") != "verified_persisted_accounting_ml_v2":
                raise ValueError("Verified persisted accounting ML v2 is unavailable for this document.")

            persisted = dict(inference.get("persisted_model") or {})
            gate = dict(inference.get("decision_gate") or {})
            partner_candidates = list(inference.get("partner_candidates") or [])[:5]
            enrichment = self.enrichment_policy.resolve(
                prediction=persisted,
                partner_candidates=partner_candidates,
            )

            defaults = {
                "journal_id": self._selected_id(list(persisted.get("journals") or [])),
                "debit_account_id": self._selected_id(list(persisted.get("debit_accounts") or [])),
                "credit_account_id": self._selected_id(list(persisted.get("credit_accounts") or [])),
                "debit_partner_id": enrichment.get("debit_partner_id"),
                "credit_partner_id": enrichment.get("credit_partner_id"),
                "debit_analytic_id": next(iter(enrichment.get("debit_analytic_distribution") or {}), None),
                "credit_analytic_id": next(iter(enrichment.get("credit_analytic_distribution") or {}), None),
                "counterpart_side": enrichment.get("counterpart_side"),
            }
            for key in ("debit_analytic_id", "credit_analytic_id"):
                if defaults[key] is not None:
                    defaults[key] = int(defaults[key])

            compact_prediction = {
                "model_version": persisted.get("model_version"),
                "bundle_sha256": persisted.get("bundle_sha256"),
                "confidence_proxy": persisted.get("confidence_proxy"),
                "move_type": list(persisted.get("move_type") or [])[:5],
                "journals": list(persisted.get("journals") or [])[:5],
                "debit_accounts": list(persisted.get("debit_accounts") or [])[:5],
                "credit_accounts": list(persisted.get("credit_accounts") or [])[:5],
                "taxes": list(persisted.get("taxes") or [])[:5],
                "analytic_accounts": list(persisted.get("analytic_accounts") or [])[:5],
            }

            return {
                "status": "success",
                "source": {
                    "filename": safe_name,
                    "mimetype": mimetype or "application/octet-stream",
                    "size_bytes": len(content),
                    "sha256": sha256,
                    "source_reference": f"DOC-SHA256:{sha256}",
                },
                "document": {
                    "document_class": document_class,
                    "fields": fields,
                    "warnings": warnings,
                    "text_preview": raw_text[:4000],
                    "detected_amount": amount,
                    "detected_entry_date": entry_date,
                    "currency": currency,
                },
                "prediction": compact_prediction,
                "decision_gate": gate,
                "partner_candidates": partner_candidates,
                "review_defaults": defaults,
                "safety": {
                    "read_only": True,
                    "erp_mutation_performed": False,
                    "human_approval_required": True,
                    "auto_posted_to_erp": False,
                    "posting_method_invoked": False,
                    "original_gate_preserved": True,
                },
            }
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
