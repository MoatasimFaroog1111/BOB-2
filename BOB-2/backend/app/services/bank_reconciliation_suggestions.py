"""Application orchestrator for hybrid bank reconciliation suggestions.

Precedence is strict and explainable:
1. Approved BOB Bank Rules.
2. Posted Odoo historical intelligence (V4 identity + candidate strategy).
3. Existing semantic accounting-learning memory.

This service is read-only and exposes no ERP posting capability.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.bank_reconciliation_accuracy_v4 import HistoricalSuggestionMatcherV4
from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_features import decimal_amount, detect_monetary_components
from app.services.bank_reconciliation_historical import OdooHistoricalBankEntryRepository
from app.services.bank_reconciliation_semantic import SemanticMemoryAdvisor, combine_advisors
from app.services.bank_rules_engine import bank_rules_engine
from app.services.bank_rules_service import bank_rules_service
from app.services.tenant_erp_service import tenant_erp_resolver

_REVIEW_THRESHOLD = 0.92


class BankReconciliationSuggestionService:
    """Coordinates independent rule, history, and semantic advisors."""

    def __init__(
        self,
        db: Session,
        context: SuggestionBatchContext,
        *,
        history_repository: OdooHistoricalBankEntryRepository | None = None,
        matcher: HistoricalSuggestionMatcherV4 | None = None,
    ):
        self.db = db
        self.context = context
        self.history_repository = history_repository or OdooHistoricalBankEntryRepository()
        self.matcher = matcher or HistoricalSuggestionMatcherV4()

    @staticmethod
    def _base(transaction: dict[str, Any]) -> dict[str, Any]:
        return {
            "row_number": transaction.get("row_number"),
            "date": str(transaction.get("date") or ""),
            "description": str(transaction.get("description") or ""),
            "amount": float(decimal_amount(transaction.get("amount"))),
            "detected_components": detect_monetary_components(transaction),
            "safe_to_post": False,
        }

    def _active_rules(self) -> list[dict[str, Any]]:
        if not self.context.bank_journal_id:
            return []
        return bank_rules_service.active_rules(
            self.db,
            organization_id=self.context.organization_id,
            journal_id=int(self.context.bank_journal_id),
            company_id=self.context.company_id,
        )

    @staticmethod
    def _is_rule_resolution(resolution: dict[str, Any] | None) -> bool:
        return bool(resolution and resolution.get("source") == "bob_bank_rule")

    def suggest(self, transactions: list[dict[str, Any]]) -> dict[str, Any]:
        if not transactions:
            return self._empty_response()

        _connection, erp = tenant_erp_resolver.resolve(self.db, self.context.organization_id)
        historical = self.history_repository.fetch(erp, self.context)
        active_rules = self._active_rules()

        staged: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]] = []
        semantic_candidates: list[int] = []
        for index, transaction in enumerate(transactions):
            base = self._base(transaction)
            rule_resolution = bank_rules_engine.resolve(transaction, active_rules) if active_rules else None
            if rule_resolution is not None:
                staged.append((base, rule_resolution, None))
                continue

            historical_resolution = self.matcher.suggest(transaction, historical)
            staged.append((base, historical_resolution, None))
            if (
                historical_resolution is None
                or float(historical_resolution.get("confidence") or 0.0) < _REVIEW_THRESHOLD
            ):
                semantic_candidates.append(index)

        semantic_budget = max(
            0,
            min(int(self.context.semantic_limit or 0), len(semantic_candidates), 100),
        )
        semantic_errors = self._fill_semantic_advice(
            transactions,
            staged,
            semantic_candidates[:semantic_budget],
        )

        items = [self._finalize(base, primary, semantic) for base, primary, semantic in staged]
        confident = sum(
            1
            for item in items
            if item.get("suggested_account_id")
            and not item.get("needs_review")
            and not item.get("advisor_conflict")
        )
        return {
            "status": "success",
            "items": items,
            "history_count": len(historical),
            "active_bank_rule_count": len(active_rules),
            "semantic_attempted_count": semantic_budget,
            "semantic_error_count": semantic_errors,
            "confident_count": confident,
            # Keep the existing public method identifier for backward compatibility.
            "method": "bob_rule_then_historical_then_semantic_v2",
            "engine_version": "v4_identity_candidate_calibration",
            "safe_to_post": False,
            "note": (
                "Approved BOB Bank Rules have deterministic priority. Remaining rows use V4 partner identity "
                "resolution plus full-corpus account candidate generation, while V3 VAT/analytic inference remains protected. "
                "A bounded semantic-memory pass handles low-confidence rows; conflicts require accountant review."
            ),
        }

    def _fill_semantic_advice(
        self,
        transactions: list[dict[str, Any]],
        staged: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]],
        indexes: list[int],
    ) -> int:
        if not indexes:
            return 0
        advisor = SemanticMemoryAdvisor(self.db, self.context.organization_id)
        errors = 0
        for index in indexes:
            try:
                semantic = advisor.suggest(
                    transactions[index],
                    company_id=self.context.company_id,
                    bank_account_id=self.context.bank_account_id,
                )
            except Exception:
                errors += 1
                semantic = None
            base, historical, _previous = staged[index]
            staged[index] = (base, historical, semantic)
        return errors

    def _finalize(
        self,
        base: dict[str, Any],
        primary: dict[str, Any] | None,
        semantic: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if self._is_rule_resolution(primary):
            resolution = dict(primary or {})
        else:
            resolution = combine_advisors(primary, semantic)
        if resolution is None:
            resolution = {
                "confidence": 0.0,
                "source": "unresolved",
                "resolution_mode": "manual_review_required",
                "reason": (
                    "No approved BOB rule or sufficiently strong historical/semantic evidence resolved this row."
                ),
                "needs_review": True,
            }
        return {**base, **resolution}

    @staticmethod
    def _empty_response() -> dict[str, Any]:
        return {
            "status": "success",
            "items": [],
            "history_count": 0,
            "active_bank_rule_count": 0,
            "semantic_attempted_count": 0,
            "semantic_error_count": 0,
            "confident_count": 0,
            "method": "bob_rule_then_historical_then_semantic_v2",
            "engine_version": "v4_identity_candidate_calibration",
            "safe_to_post": False,
        }


__all__ = [
    "BankReconciliationSuggestionService",
    "SuggestionBatchContext",
    "combine_advisors",
    "detect_monetary_components",
]
