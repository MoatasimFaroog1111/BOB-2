"""Narrow Odoo adapter for creating unposted journal-entry drafts only.

The adapter has no posting method.  It enforces idempotency by a deterministic ref,
creates only account.move records with move_type='entry', writes only validated
proposal fields, and verifies that the result remains in Odoo's draft state.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from app.core.money import money_to_erp_float, parse_money, validate_balanced_lines
from app.ml.accounting_intelligence.draft_proposal import AccountingDraftProposal


class AccountingDraftWriteError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AccountingDraftWriter(Protocol):
    def create(self, proposal: AccountingDraftProposal) -> dict[str, Any]: ...


class OdooAccountingDraftAdapter:
    """Writes exactly one balanced, unposted general journal entry to Odoo."""

    def __init__(self, erp: Any):
        self.erp = erp

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
            raise AccountingDraftWriteError(
                "ODOO_IDEMPOTENCY_LOOKUP_FAILED",
                f"Failed to check existing Odoo draft: {type(exc).__name__}.",
            ) from exc

    @staticmethod
    def _line_vals(proposal: AccountingDraftProposal) -> list[dict[str, Any]]:
        amount = parse_money(
            proposal.amount,
            field_name="amount",
            allow_negative=False,
            reject_excess_scale=True,
        )

        def build_line(line, *, debit: Decimal, credit: Decimal) -> dict[str, Any]:
            vals: dict[str, Any] = {
                "account_id": line.account_id,
                "name": line.label,
                "debit": debit,
                "credit": credit,
            }
            if line.partner_id:
                vals["partner_id"] = int(line.partner_id)
            if line.analytic_distribution:
                vals["analytic_distribution"] = dict(line.analytic_distribution)
            return vals

        source = [
            build_line(
                proposal.debit_line,
                debit=amount,
                credit=Decimal("0.00"),
            ),
            build_line(
                proposal.credit_line,
                debit=Decimal("0.00"),
                credit=amount,
            ),
        ]
        validate_balanced_lines(source)
        return [
            {
                **line,
                "debit": money_to_erp_float(line["debit"]),
                "credit": money_to_erp_float(line["credit"]),
            }
            for line in source
        ]

    def _read_created(self, move_id: int) -> dict[str, Any]:
        try:
            rows = self.erp.execute_kw(
                "account.move",
                "read",
                [[move_id]],
                {
                    "fields": [
                        "id",
                        "name",
                        "ref",
                        "state",
                        "date",
                        "journal_id",
                        "company_id",
                        "line_ids",
                    ]
                },
            ) or []
        except Exception as exc:
            raise AccountingDraftWriteError(
                "ODOO_DRAFT_VERIFY_FAILED",
                f"Odoo draft was created but could not be re-read: {type(exc).__name__}.",
            ) from exc
        if not rows:
            raise AccountingDraftWriteError(
                "ODOO_DRAFT_VERIFY_EMPTY",
                "Odoo returned no record while verifying the newly created draft.",
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

    def _verify_lines(self, move_id: int, proposal: AccountingDraftProposal) -> dict[str, Any]:
        try:
            rows = self.erp.execute_kw(
                "account.move.line",
                "search_read",
                [[["move_id", "=", int(move_id)]]],
                {
                    "fields": [
                        "id",
                        "account_id",
                        "partner_id",
                        "debit",
                        "credit",
                        "analytic_distribution",
                    ],
                    "order": "id asc",
                },
            ) or []
        except Exception as exc:
            raise AccountingDraftWriteError(
                "ODOO_DRAFT_LINE_VERIFY_FAILED",
                f"Odoo draft lines could not be verified: {type(exc).__name__}.",
            ) from exc

        by_account = {
            self._m2o_id(row.get("account_id")): row
            for row in rows
            if self._m2o_id(row.get("account_id"))
        }
        checks = []
        for expected in (proposal.debit_line, proposal.credit_line):
            actual = by_account.get(int(expected.account_id))
            if not actual:
                raise AccountingDraftWriteError(
                    "ODOO_DRAFT_ACCOUNT_LINE_MISSING",
                    f"Created Odoo draft is missing account {expected.account_code!r}.",
                )
            actual_partner = self._m2o_id(actual.get("partner_id"))
            if actual_partner != expected.partner_id:
                raise AccountingDraftWriteError(
                    "ODOO_DRAFT_PARTNER_MISMATCH",
                    f"Created Odoo draft partner does not match proposal on account {expected.account_code!r}.",
                )
            actual_analytic = actual.get("analytic_distribution") or {}
            if dict(actual_analytic) != dict(expected.analytic_distribution or {}):
                raise AccountingDraftWriteError(
                    "ODOO_DRAFT_ANALYTIC_MISMATCH",
                    f"Created Odoo draft analytic distribution does not match proposal on account {expected.account_code!r}.",
                )
            checks.append({
                "account_id": int(expected.account_id),
                "partner_id": actual_partner,
                "analytic_distribution": dict(actual_analytic),
            })
        return {"verified": True, "lines": checks}

    def create(self, proposal: AccountingDraftProposal) -> dict[str, Any]:
        existing = self._existing(proposal)
        if len(existing) > 1:
            raise AccountingDraftWriteError(
                "ODOO_DUPLICATE_IDEMPOTENCY_REF",
                "More than one Odoo move already uses the deterministic ML draft reference.",
            )
        if existing:
            row = existing[0]
            if str(row.get("state") or "") != "draft":
                raise AccountingDraftWriteError(
                    "ODOO_IDEMPOTENCY_REF_NOT_DRAFT",
                    "The deterministic ML draft reference already belongs to a non-draft Odoo move.",
                )
            enrichment_verification = self._verify_lines(int(row["id"]), proposal)
            return {
                "created": False,
                "idempotent_reuse": True,
                "move_id": int(row["id"]),
                "entry_number": row.get("name") or "",
                "state": "draft",
                "ref": proposal.idempotency_ref,
                "enrichment_verification": enrichment_verification,
            }

        line_vals = self._line_vals(proposal)
        move_vals = {
            "move_type": "entry",
            "company_id": proposal.company_id,
            "journal_id": proposal.journal_id,
            "date": proposal.entry_date,
            "ref": proposal.idempotency_ref,
            "line_ids": [(0, 0, line) for line in line_vals],
        }
        try:
            move_id = self.erp.execute_kw("account.move", "create", [move_vals])
            if isinstance(move_id, list):
                move_id = move_id[0]
            move_id = int(move_id)
        except Exception as exc:
            raise AccountingDraftWriteError(
                "ODOO_DRAFT_CREATE_FAILED",
                f"Failed to create Odoo journal-entry draft: {type(exc).__name__}.",
            ) from exc

        row = self._read_created(move_id)
        state = str(row.get("state") or "")
        if state != "draft":
            raise AccountingDraftWriteError(
                "ODOO_CREATED_MOVE_NOT_DRAFT",
                f"Safety verification failed: created Odoo move state is {state!r}, not 'draft'.",
            )
        if str(row.get("ref") or "") != proposal.idempotency_ref:
            raise AccountingDraftWriteError(
                "ODOO_DRAFT_REF_MISMATCH",
                "Safety verification failed: Odoo draft reference does not match the idempotency reference.",
            )

        enrichment_verification = self._verify_lines(move_id, proposal)
        return {
            "created": True,
            "idempotent_reuse": False,
            "move_id": move_id,
            "entry_number": row.get("name") or "",
            "state": state,
            "ref": proposal.idempotency_ref,
            "line_count": len(row.get("line_ids") or []),
            "enrichment_verification": enrichment_verification,
        }
