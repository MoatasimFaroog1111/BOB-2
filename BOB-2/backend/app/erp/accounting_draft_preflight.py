"""Read-only Odoo preflight for persisted-ML journal-entry drafts.

This component validates that a gated proposal still resolves against the live Odoo
company, journal, and accounts immediately before any mutation is allowed.  It never
calls create/write/unlink/action_post and therefore cannot change ERP state.
"""

from __future__ import annotations

from typing import Any

from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposal


class AccountingDraftPreflightError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class OdooAccountingDraftPreflight:
    """Validate one ML draft proposal using read-only Odoo calls only."""

    def __init__(self, erp: Any):
        self.erp = erp

    def _read_one(
        self,
        model: str,
        record_id: int,
        *,
        fields: list[str],
        code: str,
    ) -> dict[str, Any]:
        try:
            rows = self.erp.execute_kw(
                model,
                "search_read",
                [[["id", "=", int(record_id)]]],
                {"fields": fields, "limit": 1},
            ) or []
        except Exception as exc:
            raise AccountingDraftPreflightError(
                f"{code}_READ_FAILED",
                f"Failed to read live Odoo {model}: {type(exc).__name__}.",
            ) from exc
        if not rows:
            raise AccountingDraftPreflightError(
                f"{code}_NOT_FOUND",
                f"The referenced live Odoo {model} record no longer exists.",
            )
        return dict(rows[0])

    @staticmethod
    def _m2o_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            try:
                return int(value[0]) if value[0] else None
            except (TypeError, ValueError):
                return None
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def _company(self, company_id: int) -> dict[str, Any]:
        row = self._read_one(
            "res.company",
            company_id,
            fields=["id", "name"],
            code="COMPANY",
        )
        return {"id": int(row["id"]), "name": str(row.get("name") or "")}

    def _journal(self, proposal: AccountingDraftProposal) -> dict[str, Any]:
        row = self._read_one(
            "account.journal",
            proposal.journal_id,
            fields=["id", "code", "name", "type", "company_id", "active"],
            code="JOURNAL",
        )
        company_id = self._m2o_id(row.get("company_id"))
        if company_id and company_id != proposal.company_id:
            raise AccountingDraftPreflightError(
                "JOURNAL_COMPANY_MISMATCH",
                "The selected Odoo journal belongs to a different company.",
            )
        if row.get("active") is False:
            raise AccountingDraftPreflightError(
                "JOURNAL_INACTIVE",
                "The selected Odoo journal is inactive.",
            )
        journal_type = str(row.get("type") or "").strip().lower()
        if journal_type not in {"bank", "cash", "general"}:
            raise AccountingDraftPreflightError(
                "JOURNAL_TYPE_NOT_AUTOMATED",
                "The selected live Odoo journal is not bank, cash, or general.",
            )
        return {
            "id": int(row["id"]),
            "code": str(row.get("code") or ""),
            "name": str(row.get("name") or ""),
            "type": journal_type,
            "company_id": company_id,
        }

    def _account(self, account_id: int, *, side: str) -> dict[str, Any]:
        row = self._read_one(
            "account.account",
            account_id,
            fields=["id", "code", "name", "company_ids", "deprecated"],
            code=f"{side.upper()}_ACCOUNT",
        )
        if bool(row.get("deprecated")):
            raise AccountingDraftPreflightError(
                f"{side.upper()}_ACCOUNT_DEPRECATED",
                f"The selected {side} account is deprecated in Odoo.",
            )
        company_ids = {
            int(value)
            for value in (row.get("company_ids") or [])
            if isinstance(value, int) and value > 0
        }
        return {
            "id": int(row["id"]),
            "code": str(row.get("code") or ""),
            "name": str(row.get("name") or ""),
            "company_ids": sorted(company_ids),
        }

    def _existing(self, proposal: AccountingDraftProposal) -> list[dict[str, Any]]:
        try:
            return self.erp.execute_kw(
                "account.move",
                "search_read",
                [[
                    ["ref", "=", proposal.idempotency_ref],
                    ["company_id", "=", proposal.company_id],
                ]],
                {
                    "fields": ["id", "name", "ref", "state", "date", "journal_id", "company_id"],
                    "limit": 2,
                },
            ) or []
        except Exception as exc:
            raise AccountingDraftPreflightError(
                "IDEMPOTENCY_LOOKUP_FAILED",
                f"Failed to check the live Odoo idempotency reference: {type(exc).__name__}.",
            ) from exc

    def inspect(self, proposal: AccountingDraftProposal) -> dict[str, Any]:
        company = self._company(proposal.company_id)
        journal = self._journal(proposal)
        debit = self._account(proposal.debit_line.account_id, side="debit")
        credit = self._account(proposal.credit_line.account_id, side="credit")

        for side, account in (("debit", debit), ("credit", credit)):
            company_ids = set(account.get("company_ids") or [])
            if company_ids and proposal.company_id not in company_ids:
                raise AccountingDraftPreflightError(
                    f"{side.upper()}_ACCOUNT_COMPANY_MISMATCH",
                    f"The selected {side} account is not available to the requested Odoo company.",
                )

        existing = self._existing(proposal)
        if len(existing) > 1:
            raise AccountingDraftPreflightError(
                "DUPLICATE_IDEMPOTENCY_REFERENCE",
                "More than one Odoo move already uses the deterministic ML reference.",
            )
        existing_summary = None
        if existing:
            row = dict(existing[0])
            existing_summary = {
                "move_id": int(row["id"]),
                "entry_number": str(row.get("name") or ""),
                "state": str(row.get("state") or ""),
                "ref": str(row.get("ref") or ""),
            }
            if existing_summary["state"] != "draft":
                raise AccountingDraftPreflightError(
                    "IDEMPOTENCY_REFERENCE_ALREADY_POSTED",
                    "The deterministic ML reference already belongs to a non-draft Odoo move.",
                )

        return {
            "status": "pass",
            "read_only": True,
            "mutation_methods_invoked": False,
            "company": company,
            "journal": journal,
            "debit_account": debit,
            "credit_account": credit,
            "idempotency": {
                "ref": proposal.idempotency_ref,
                "existing_draft": existing_summary,
                "safe_to_create": existing_summary is None,
                "safe_to_reuse": existing_summary is not None,
            },
            "proposal_model_version": proposal.model_version,
            "proposal_bundle_sha256": proposal.bundle_sha256,
        }
