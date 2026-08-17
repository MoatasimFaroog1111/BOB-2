"""Conservative enrichment policy for accounting draft lines.

This module is intentionally pure: it never talks to Odoo and never mutates ERP
state.  It decides whether partner and analytic suggestions are strong enough to
be included in an already-approved draft proposal.  Live-reference validation is
performed separately by the Odoo preflight adapter.
"""

from __future__ import annotations

from typing import Any


class AccountingDraftEnrichmentPolicy:
    """Resolve optional line enrichment without weakening the accounting gate."""

    PARTNER_MIN_CONFIDENCE = 0.85
    PARTNER_MIN_MARGIN = 0.15
    ANALYTIC_MIN_SCORE = 0.80

    @staticmethod
    def _selected(prediction: dict[str, Any], key: str) -> list[dict[str, Any]]:
        return [dict(row) for row in (prediction.get(key) or []) if row.get("selected")]

    @staticmethod
    def _selected_account(prediction: dict[str, Any], key: str) -> dict[str, Any] | None:
        selected = AccountingDraftEnrichmentPolicy._selected(prediction, key)
        return selected[0] if len(selected) == 1 else None

    @staticmethod
    def _is_bank_account(candidate: dict[str, Any] | None) -> bool:
        if not candidate:
            return False
        return str(candidate.get("account_type") or "").strip().lower() == "asset_cash"

    @staticmethod
    def _counterpart_side(prediction: dict[str, Any]) -> str | None:
        debit = AccountingDraftEnrichmentPolicy._selected_account(prediction, "debit_accounts")
        credit = AccountingDraftEnrichmentPolicy._selected_account(prediction, "credit_accounts")
        debit_bank = AccountingDraftEnrichmentPolicy._is_bank_account(debit)
        credit_bank = AccountingDraftEnrichmentPolicy._is_bank_account(credit)
        if debit_bank and not credit_bank:
            return "credit"
        if credit_bank and not debit_bank:
            return "debit"
        return None

    @staticmethod
    def _partner_candidate(partner_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [
            dict(row)
            for row in partner_candidates
            if row.get("live_reference_resolved") and row.get("id")
        ]
        candidates.sort(key=lambda row: float(row.get("confidence") or 0.0), reverse=True)
        if not candidates:
            return None
        top = candidates[0]
        top_score = float(top.get("confidence") or 0.0)
        if top_score < AccountingDraftEnrichmentPolicy.PARTNER_MIN_CONFIDENCE:
            return None
        if len(candidates) > 1:
            second = float(candidates[1].get("confidence") or 0.0)
            if top_score - second < AccountingDraftEnrichmentPolicy.PARTNER_MIN_MARGIN:
                return None
        return top

    @staticmethod
    def _analytic_candidate(prediction: dict[str, Any]) -> dict[str, Any] | None:
        selected = AccountingDraftEnrichmentPolicy._selected(prediction, "analytic_accounts")
        if len(selected) != 1:
            return None
        candidate = selected[0]
        if not candidate.get("live_reference_resolved") or not candidate.get("id"):
            return None
        if float(candidate.get("model_score") or 0.0) < AccountingDraftEnrichmentPolicy.ANALYTIC_MIN_SCORE:
            return None
        return candidate

    def resolve(
        self,
        *,
        prediction: dict[str, Any],
        partner_candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        counterpart = self._counterpart_side(prediction)
        partner = self._partner_candidate(list(partner_candidates or []))
        analytic = self._analytic_candidate(prediction)

        result: dict[str, Any] = {
            "debit_partner_id": None,
            "credit_partner_id": None,
            "debit_analytic_distribution": {},
            "credit_analytic_distribution": {},
            "auto_applied": [],
            "not_auto_applied": [],
            "counterpart_side": counterpart,
        }

        if counterpart and partner:
            result[f"{counterpart}_partner_id"] = int(partner["id"])
            result["auto_applied"].append("partner")
        else:
            result["not_auto_applied"].append("partner")

        if counterpart and analytic:
            result[f"{counterpart}_analytic_distribution"] = {str(int(analytic["id"])): 100.0}
            result["auto_applied"].append("analytic_distribution")
        else:
            result["not_auto_applied"].append("analytic_distribution")

        return result
