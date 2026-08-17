"""Pure construction of safe Odoo journal-entry draft proposals.

This module converts an already-gated persisted-model prediction into a minimal
accounting proposal.  It deliberately does not own ERP credentials or mutation
methods.  Optional partner/analytic enrichment is accepted only from the separate
conservative enrichment policy and is revalidated against live Odoo before write.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.money import MoneyValidationError, money_to_str, parse_money


class AccountingDraftProposalError(ValueError):
    """Raised when a model result is not safe enough to materialize as a draft."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AccountingDraftLineProposal:
    side: str
    account_id: int
    account_code: str
    account_name: str
    amount: str
    label: str
    partner_id: int | None = None
    analytic_distribution: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountingDraftProposal:
    model_version: str
    bundle_sha256: str
    source_reference: str
    idempotency_ref: str
    company_id: int
    entry_date: str
    move_type: str
    journal_id: int
    journal_code: str
    journal_name: str
    journal_type: str
    description: str
    amount: str
    debit_line: AccountingDraftLineProposal
    credit_line: AccountingDraftLineProposal
    recommendations: dict[str, Any]
    review_required_after_creation: bool = True
    auto_post_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AccountingDraftProposalBuilder:
    """Builds a deterministic, non-posting proposal from model output."""

    ALLOWED_MOVE_TYPES = frozenset({"entry"})
    ALLOWED_JOURNAL_TYPES = frozenset({"bank", "cash", "general"})

    @staticmethod
    def _top(prediction: dict[str, Any], key: str) -> dict[str, Any] | None:
        values = prediction.get(key) or []
        return values[0] if values else None

    @staticmethod
    def _selected(prediction: dict[str, Any], key: str) -> list[dict[str, Any]]:
        return [row for row in prediction.get(key, []) if row.get("selected")]

    @staticmethod
    def _validated_date(value: str) -> str:
        try:
            return date.fromisoformat(str(value)).isoformat()
        except Exception as exc:
            raise AccountingDraftProposalError(
                "ENTRY_DATE_INVALID",
                "A valid explicit ISO accounting date is required for draft creation.",
            ) from exc

    @staticmethod
    def _validated_amount(value: Any) -> Decimal:
        try:
            amount = parse_money(
                value,
                field_name="amount",
                allow_negative=False,
                reject_excess_scale=True,
            )
        except MoneyValidationError as exc:
            raise AccountingDraftProposalError("AMOUNT_INVALID", str(exc)) from exc
        if amount <= Decimal("0.00"):
            raise AccountingDraftProposalError(
                "AMOUNT_NOT_POSITIVE",
                "Draft creation requires a positive accounting amount.",
            )
        return amount

    @staticmethod
    def _idempotency_ref(*, company_id: int, source_reference: str) -> str:
        normalized = str(source_reference or "").strip()
        if len(normalized) < 3:
            raise AccountingDraftProposalError(
                "SOURCE_REFERENCE_REQUIRED",
                "A stable source reference is required to prevent duplicate Odoo drafts.",
            )
        digest = hashlib.sha256(f"{company_id}:{normalized}".encode("utf-8")).hexdigest()[:24]
        return f"BOB-MLV2-{digest}"

    @staticmethod
    def _resolved_identifier(candidate: dict[str, Any] | None, *, code: str) -> int:
        if not candidate or not candidate.get("live_reference_resolved"):
            raise AccountingDraftProposalError(
                f"{code}_LIVE_REFERENCE_REQUIRED",
                f"{code.replace('_', ' ').title()} must resolve against the live ERP catalog.",
            )
        try:
            return int(candidate["id"])
        except Exception as exc:
            raise AccountingDraftProposalError(
                f"{code}_ID_INVALID",
                f"{code.replace('_', ' ').title()} has no valid live ERP identifier.",
            ) from exc

    @staticmethod
    def _validated_partner(value: Any) -> int | None:
        if value in (None, False, ""):
            return None
        try:
            partner_id = int(value)
        except (TypeError, ValueError) as exc:
            raise AccountingDraftProposalError(
                "PARTNER_ID_INVALID",
                "Partner enrichment must contain a positive live Odoo partner ID.",
            ) from exc
        if partner_id <= 0:
            raise AccountingDraftProposalError(
                "PARTNER_ID_INVALID",
                "Partner enrichment must contain a positive live Odoo partner ID.",
            )
        return partner_id

    @staticmethod
    def _validated_analytic_distribution(value: Any) -> dict[str, float]:
        if value in (None, False, ""):
            return {}
        if not isinstance(value, dict):
            raise AccountingDraftProposalError(
                "ANALYTIC_DISTRIBUTION_INVALID",
                "Analytic distribution must be an Odoo-compatible mapping.",
            )
        clean: dict[str, float] = {}
        total = Decimal("0")
        for raw_key, raw_share in value.items():
            key = str(raw_key or "").strip()
            if not key:
                raise AccountingDraftProposalError(
                    "ANALYTIC_DISTRIBUTION_INVALID",
                    "Analytic distribution contains an empty account key.",
                )
            try:
                share = Decimal(str(raw_share))
            except Exception as exc:
                raise AccountingDraftProposalError(
                    "ANALYTIC_DISTRIBUTION_INVALID",
                    "Analytic distribution contains a non-numeric percentage.",
                ) from exc
            if share <= 0 or share > 100:
                raise AccountingDraftProposalError(
                    "ANALYTIC_DISTRIBUTION_INVALID",
                    "Analytic percentages must be greater than zero and at most 100.",
                )
            total += share
            clean[key] = float(share)
        if clean and abs(total - Decimal("100")) > Decimal("0.01"):
            raise AccountingDraftProposalError(
                "ANALYTIC_DISTRIBUTION_NOT_100",
                "Analytic distribution must total 100 percent.",
            )
        return clean

    def build(
        self,
        *,
        prediction: dict[str, Any],
        decision_gate: dict[str, Any],
        amount: Any,
        company_id: int,
        source_reference: str,
        entry_date: str,
        description: str | None = None,
        partner_candidates: list[dict[str, Any]] | None = None,
        enrichment: dict[str, Any] | None = None,
    ) -> AccountingDraftProposal:
        if not bool(decision_gate.get("draft_eligible")):
            raise AccountingDraftProposalError(
                "DECISION_GATE_BLOCKED",
                "The deterministic accounting safety gate requires accountant review.",
            )
        if bool(decision_gate.get("auto_post_allowed")):
            raise AccountingDraftProposalError(
                "AUTO_POST_POLICY_VIOLATION",
                "Persisted accounting ML is not allowed to auto-post ERP entries.",
            )
        if int(company_id) <= 0:
            raise AccountingDraftProposalError(
                "COMPANY_ID_REQUIRED",
                "A positive explicit company_id is required for Odoo draft creation.",
            )

        move = self._top(prediction, "move_type") or {}
        move_type = str(move.get("label") or "")
        if move_type not in self.ALLOWED_MOVE_TYPES:
            raise AccountingDraftProposalError(
                "MOVE_TYPE_NOT_AUTOMATED",
                "Only general journal-entry classification is eligible for automated draft creation.",
            )

        journal = self._top(prediction, "journals")
        journal_id = self._resolved_identifier(journal, code="JOURNAL")
        journal_type = str((journal or {}).get("type") or "").lower()
        if journal_type not in self.ALLOWED_JOURNAL_TYPES:
            raise AccountingDraftProposalError(
                "JOURNAL_TYPE_NOT_AUTOMATED",
                "Only bank, cash, or general journals are eligible for automated draft creation.",
            )

        debit_selected = self._selected(prediction, "debit_accounts")
        credit_selected = self._selected(prediction, "credit_accounts")
        if len(debit_selected) != 1 or len(credit_selected) != 1:
            raise AccountingDraftProposalError(
                "DOUBLE_ENTRY_NOT_SINGLE",
                "Exactly one selected debit and one selected credit account are required.",
            )
        debit = debit_selected[0]
        credit = credit_selected[0]
        debit_id = self._resolved_identifier(debit, code="DEBIT_ACCOUNT")
        credit_id = self._resolved_identifier(credit, code="CREDIT_ACCOUNT")
        if debit_id == credit_id:
            raise AccountingDraftProposalError(
                "CONTRADICTORY_ACCOUNT_SIDES",
                "Debit and credit accounts cannot be identical.",
            )

        if self._selected(prediction, "taxes"):
            raise AccountingDraftProposalError(
                "TAX_AUTOMATION_NOT_ENABLED",
                "A tax label was selected; tax-bearing documents require accountant review.",
            )

        parsed_amount = self._validated_amount(amount)
        accounting_date = self._validated_date(entry_date)
        text_label = str(description or source_reference or "BOB accounting ML draft").strip()[:500]
        if not text_label:
            text_label = "BOB accounting ML draft"

        idempotency_ref = self._idempotency_ref(
            company_id=int(company_id),
            source_reference=source_reference,
        )

        enrichment_payload = dict(enrichment or {})
        debit_partner_id = self._validated_partner(enrichment_payload.get("debit_partner_id"))
        credit_partner_id = self._validated_partner(enrichment_payload.get("credit_partner_id"))
        debit_analytic = self._validated_analytic_distribution(
            enrichment_payload.get("debit_analytic_distribution")
        )
        credit_analytic = self._validated_analytic_distribution(
            enrichment_payload.get("credit_analytic_distribution")
        )

        recommendations = {
            "partner_candidates": list(partner_candidates or [])[:5],
            "analytic_accounts": list(prediction.get("analytic_accounts") or [])[:5],
            "taxes": list(prediction.get("taxes") or [])[:5],
            "enrichment_policy": enrichment_payload,
            "not_auto_applied": list(enrichment_payload.get("not_auto_applied") or ["partner", "analytic_distribution", "tax"]),
        }
        if "tax" not in recommendations["not_auto_applied"]:
            recommendations["not_auto_applied"].append("tax")

        return AccountingDraftProposal(
            model_version=str(prediction.get("model_version") or ""),
            bundle_sha256=str(prediction.get("bundle_sha256") or ""),
            source_reference=str(source_reference).strip(),
            idempotency_ref=idempotency_ref,
            company_id=int(company_id),
            entry_date=accounting_date,
            move_type="entry",
            journal_id=journal_id,
            journal_code=str((journal or {}).get("code") or (journal or {}).get("label") or ""),
            journal_name=str((journal or {}).get("name") or ""),
            journal_type=journal_type,
            description=text_label,
            amount=money_to_str(parsed_amount),
            debit_line=AccountingDraftLineProposal(
                side="debit",
                account_id=debit_id,
                account_code=str(debit.get("code") or debit.get("label") or ""),
                account_name=str(debit.get("name") or ""),
                amount=money_to_str(parsed_amount),
                label=text_label,
                partner_id=debit_partner_id,
                analytic_distribution=debit_analytic,
            ),
            credit_line=AccountingDraftLineProposal(
                side="credit",
                account_id=credit_id,
                account_code=str(credit.get("code") or credit.get("label") or ""),
                account_name=str(credit.get("name") or ""),
                amount=money_to_str(parsed_amount),
                label=text_label,
                partner_id=credit_partner_id,
                analytic_distribution=credit_analytic,
            ),
            recommendations=recommendations,
        )
