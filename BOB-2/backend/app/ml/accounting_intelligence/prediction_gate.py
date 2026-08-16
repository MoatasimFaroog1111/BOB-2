"""Deterministic safety gate for persisted accounting predictions."""

from __future__ import annotations

from typing import Any


class AccountingPredictionGate:
    """Decides review vs draft eligibility without mutating an ERP."""

    MOVE_TYPE_MIN = 0.75
    JOURNAL_MIN = 0.75
    DEBIT_MIN = 0.65
    CREDIT_MIN = 0.70

    @staticmethod
    def _top(prediction: dict[str, Any], key: str) -> dict[str, Any] | None:
        values = prediction.get(key) or []
        return values[0] if values else None

    def evaluate(self, prediction: dict[str, Any], *, amount: float | None) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        required = {
            "move_type": self._top(prediction, "move_type"),
            "journal": self._top(prediction, "journals"),
            "debit": self._top(prediction, "debit_accounts"),
            "credit": self._top(prediction, "credit_accounts"),
        }
        thresholds = {
            "move_type": self.MOVE_TYPE_MIN,
            "journal": self.JOURNAL_MIN,
            "debit": self.DEBIT_MIN,
            "credit": self.CREDIT_MIN,
        }

        for name, candidate in required.items():
            if not candidate:
                findings.append({"code": f"{name.upper()}_UNRESOLVED", "severity": "high"})
                continue
            score = float(candidate.get("model_score") or 0.0)
            if score < thresholds[name]:
                findings.append({
                    "code": f"{name.upper()}_LOW_SCORE",
                    "severity": "medium",
                    "score": round(score, 6),
                    "minimum": thresholds[name],
                })
            if name in {"journal", "debit", "credit"} and not candidate.get("live_reference_resolved"):
                findings.append({
                    "code": f"{name.upper()}_LIVE_REFERENCE_UNRESOLVED",
                    "severity": "high",
                    "label": candidate.get("label"),
                })

        debit_selected = [x for x in prediction.get("debit_accounts", []) if x.get("selected")]
        credit_selected = [x for x in prediction.get("credit_accounts", []) if x.get("selected")]
        if len(debit_selected) != 1 or len(credit_selected) != 1:
            findings.append({
                "code": "NON_SINGLE_DOUBLE_ENTRY_CLASSIFICATION",
                "severity": "high",
                "debit_selected": len(debit_selected),
                "credit_selected": len(credit_selected),
            })
        elif debit_selected[0].get("id") == credit_selected[0].get("id"):
            findings.append({
                "code": "CONTRADICTORY_ACCOUNT_SIDES",
                "severity": "high",
                "account_id": debit_selected[0].get("id"),
            })

        if amount is None:
            findings.append({"code": "AMOUNT_REQUIRED_FOR_DRAFT", "severity": "high"})
        elif float(amount) == 0.0:
            findings.append({"code": "ZERO_AMOUNT_REQUIRES_REVIEW", "severity": "high"})

        blocking = [item for item in findings if item["severity"] in {"high", "medium"}]
        return {
            "draft_eligible": not blocking,
            "review_required": bool(blocking),
            "auto_post_allowed": False,
            "findings": findings,
            "policy": {
                "move_type_min": self.MOVE_TYPE_MIN,
                "journal_min": self.JOURNAL_MIN,
                "debit_min": self.DEBIT_MIN,
                "credit_min": self.CREDIT_MIN,
                "single_debit_credit_required": True,
                "explicit_amount_required": True,
            },
        }
