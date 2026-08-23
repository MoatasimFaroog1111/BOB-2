"""Semantic-memory adapter and advisor ensemble for bank reconciliation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.accounting_intelligence import AccountingIntelligenceService
from app.services.bank_reconciliation_features import decimal_amount, transaction_text

_REVIEW_THRESHOLD = 0.92


class SemanticMemoryAdvisor:
    """Adapter over the existing learned accounting memory."""

    def __init__(self, db: Session, organization_id: int):
        self._service = AccountingIntelligenceService(db)
        self._organization_id = organization_id

    @staticmethod
    def _candidate_bucket(prediction: dict[str, Any], amount: Any) -> list[dict[str, Any]]:
        value = decimal_amount(amount)
        if value < 0:
            return list(prediction.get("debit_accounts") or [])
        if value > 0:
            return list(prediction.get("credit_accounts") or [])
        candidates = list(prediction.get("debit_accounts") or []) + list(
            prediction.get("credit_accounts") or []
        )
        candidates.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
        return candidates

    def suggest(
        self,
        transaction: dict[str, Any],
        *,
        company_id: int | None,
        bank_account_id: int | None,
    ) -> dict[str, Any] | None:
        text = transaction_text(transaction)
        if len(text.strip()) < 4:
            return None
        prediction = self._service.predict(
            organization_id=self._organization_id,
            text=text,
            amount=float(decimal_amount(transaction.get("amount"))),
            move_type_hint="entry",
            currency_hint="SAR",
            top_k=12,
            company_id=company_id,
        )
        candidates = [
            item
            for item in self._candidate_bucket(prediction, transaction.get("amount"))
            if int(item.get("id") or 0) > 0
            and (not bank_account_id or int(item.get("id") or 0) != int(bank_account_id))
        ]
        if not candidates:
            return None
        candidate = candidates[0]
        confidence = float(candidate.get("confidence") or 0.0)
        partner = next(iter(prediction.get("partners") or []), {})
        analytic = next(iter(prediction.get("analytic_accounts") or []), {})
        return {
            "suggested_account_id": int(candidate["id"]),
            "suggested_account_label": " ".join(
                str(part) for part in (candidate.get("code"), candidate.get("name")) if part
            ).strip(),
            "suggested_partner_id": int(partner.get("id") or 0) or None,
            "suggested_partner_label": str(partner.get("name") or ""),
            "suggested_analytic_account_id": int(analytic.get("id") or 0) or None,
            "suggested_analytic_account_label": " ".join(
                str(part) for part in (analytic.get("code"), analytic.get("name")) if part
            ).strip(),
            "confidence": round(confidence, 4),
            "source": "accounting_intelligence_memory",
            "resolution_mode": "semantic_structured_learning",
            "reason": (
                "Existing accounting-intelligence memory selected the counterpart account using semantic embeddings, "
                "structured accounting features, historical outcomes, and live chart semantics."
            ),
            "confidence_breakdown": {
                "semantic_structured_confidence": round(confidence, 4),
                "evidence_strength": float(prediction.get("evidence_strength") or 0.0),
                "historical_consensus": float(candidate.get("historical_consensus") or 0.0),
            },
            "alternatives": [
                {
                    "account_id": int(item.get("id") or 0),
                    "account_label": " ".join(
                        str(part) for part in (item.get("code"), item.get("name")) if part
                    ).strip(),
                    "confidence": float(item.get("confidence") or 0.0),
                }
                for item in candidates[:3]
            ],
            "audit_findings": prediction.get("audit_findings") or [],
            "needs_review": confidence < _REVIEW_THRESHOLD,
        }


def _merge_nonempty(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    result = dict(primary)
    for key in (
        "suggested_partner_id",
        "suggested_partner_label",
        "suggested_analytic_account_id",
        "suggested_analytic_account_label",
    ):
        if not result.get(key) and secondary.get(key):
            result[key] = secondary[key]
    return result


def combine_advisors(
    historical: dict[str, Any] | None,
    semantic: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if historical is None:
        return semantic
    if semantic is None:
        return historical

    historical_account = int(historical.get("suggested_account_id") or 0)
    semantic_account = int(semantic.get("suggested_account_id") or 0)
    historical_confidence = float(historical.get("confidence") or 0.0)
    semantic_confidence = float(semantic.get("confidence") or 0.0)

    if historical_account and historical_account == semantic_account:
        winner = _merge_nonempty(historical, semantic)
        combined = min(
            0.99,
            max(historical_confidence, semantic_confidence)
            + 0.20 * min(historical_confidence, semantic_confidence),
        )
        winner.update(
            {
                "confidence": round(combined, 4),
                "source": "historical_semantic_consensus",
                "resolution_mode": "ensemble_agreement",
                "reason": (
                    "Direct posted bank-history consensus and semantic accounting memory independently selected the same "
                    f"counterpart account {historical_account}."
                ),
                "advisor_agreement": True,
                "needs_review": combined < _REVIEW_THRESHOLD,
            }
        )
        winner["confidence_breakdown"] = {
            "historical": round(historical_confidence, 4),
            "semantic": round(semantic_confidence, 4),
        }
        return winner

    historical_wins = historical_confidence >= semantic_confidence
    winner = dict(historical if historical_wins else semantic)
    loser = semantic if historical_wins else historical
    margin = abs(historical_confidence - semantic_confidence)
    winner.update(
        {
            "advisor_agreement": False,
            "advisor_conflict": {
                "historical_account_id": historical_account or None,
                "historical_confidence": round(historical_confidence, 4),
                "semantic_account_id": semantic_account or None,
                "semantic_confidence": round(semantic_confidence, 4),
                "confidence_margin": round(margin, 4),
            },
            "needs_review": True,
            "reason": (
                f"Historical and semantic advisors disagreed. The higher-confidence {winner.get('source')} candidate is "
                "shown for review; automatic acceptance is blocked."
            ),
        }
    )
    return _merge_nonempty(winner, loser)
