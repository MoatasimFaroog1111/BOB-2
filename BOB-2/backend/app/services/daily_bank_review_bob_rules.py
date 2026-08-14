"""BOB Bank Rules implementation of the existing daily review workflow.

The established review/audit lifecycle stays closed for modification. This adapter adds
BOB-owned tax splitting while Odoo remains the source of truth for referenced accounts.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import MONEY_ZERO, money_to_str, parse_money
from app.erp.bank_reconciliation import parse_file
from app.services.bank_rule_tax import BankRuleTaxError, split_tax_inclusive
from app.services.bank_rule_tax_audit import TaxAwareAccountingAuditEngine
from app.services.daily_bank_context import BOBDailyBankContextLoader, bob_daily_bank_context_loader
from app.services.daily_bank_entry_builder import BankJournalContext, DailyBankEntryBuilder, DailyBankEntryBuildError
from app.services.daily_bank_review_service import DailyBankReviewService


class BOBTaxAwareDailyBankEntryBuilder(DailyBankEntryBuilder):
    """Decorate strict BOB rule resolutions with explicit tax journal lines."""

    @staticmethod
    def _mark_tax_failure(lines: list[dict[str, Any]], *, tax_id: int, error: str) -> None:
        for line in lines:
            line["needs_review"] = True
            line["tax_resolution_failed"] = True
            line["tax_id"] = int(tax_id)
            line["tax_error"] = error

    def _build_transaction_lines(
        self,
        transaction: dict[str, Any],
        *,
        rules: list[dict[str, Any]],
        journal: BankJournalContext,
        account_catalog: Mapping[int, Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        lines, unresolved, needs_review = super()._build_transaction_lines(
            transaction, rules=rules, journal=journal, account_catalog=account_catalog
        )
        if len(lines) != 2:
            return lines, unresolved, needs_review
        counterpart = dict(lines[1])
        rule_id = counterpart.get("bank_rule_id")
        if not rule_id or counterpart.get("account_id") is None:
            return lines, unresolved, needs_review
        matched = next((row for row in rules if int(row.get("rule_id") or 0) == int(rule_id)), None)
        target = dict((matched or {}).get("target") or {})
        tax_id = int(target.get("tax_id") or 0)
        if tax_id <= 0:
            return lines, unresolved, needs_review

        tax_account_id = int(target.get("tax_account_id") or 0)
        tax_account = account_catalog.get(tax_account_id) or {}
        tax_code = str(tax_account.get("code") or "").strip()
        tax_account_name = str(tax_account.get("name") or "").strip()
        if (
            tax_account_id <= 0
            or not tax_code
            or not tax_account_name
            or str(target.get("tax_amount_type") or "") != "percent"
            or str(target.get("tax_amount_mode") or "") != "included_in_bank_amount"
        ):
            self._mark_tax_failure(
                lines,
                tax_id=tax_id,
                error="Approved Bank Rule tax metadata is incomplete or no longer resolvable in Odoo.",
            )
            return lines, True, True

        amount = parse_money(transaction["amount"], field_name="bank_transaction.amount")
        try:
            split = split_tax_inclusive(amount, target.get("tax_rate"))
        except BankRuleTaxError as exc:
            self._mark_tax_failure(lines, tax_id=tax_id, error=str(exc))
            return lines, True, True

        bank_line = dict(lines[0])
        if amount < MONEY_ZERO:
            counterpart["debit"] = money_to_str(split.base)
            counterpart["credit"] = money_to_str(MONEY_ZERO)
            tax_debit, tax_credit = split.tax, MONEY_ZERO
        else:
            counterpart["debit"] = money_to_str(MONEY_ZERO)
            counterpart["credit"] = money_to_str(split.base)
            tax_debit, tax_credit = MONEY_ZERO, split.tax

        tax_metadata = {
            "tax_id": tax_id,
            "tax_name": str(target.get("tax_name") or ""),
            "tax_rate": str(target.get("tax_rate") or ""),
            "tax_amount_type": "percent",
            "tax_type_use": str(target.get("tax_type_use") or ""),
            "tax_amount_mode": "included_in_bank_amount",
            "tax_gross_amount": money_to_str(split.gross),
            "tax_base_amount": money_to_str(split.base),
            "tax_amount": money_to_str(split.tax),
        }
        counterpart.update(tax_metadata)
        tax_line = {
            **bank_line,
            **tax_metadata,
            "role": "tax",
            "account_id": tax_account_id,
            "account_code": tax_code,
            "account_name": tax_account_name,
            "debit": money_to_str(tax_debit),
            "credit": money_to_str(tax_credit),
            "name": f"{str(target.get('tax_name') or 'Tax')} — {str(transaction.get('description') or '')}"[:255],
            "partner_id": counterpart.get("partner_id"),
            "partner_name": counterpart.get("partner_name") or "",
            "analytic_account_id": None,
            "analytic_account_name": "",
            "needs_review": needs_review,
        }
        return [bank_line, counterpart, tax_line], unresolved, needs_review


class BOBRulesDailyBankReviewService(DailyBankReviewService):
    def __init__(
        self,
        *,
        bob_context_loader: BOBDailyBankContextLoader | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("builder", BOBTaxAwareDailyBankEntryBuilder())
        kwargs.setdefault("auditor", TaxAwareAccountingAuditEngine())
        super().__init__(**kwargs)
        self._bob_context_loader = bob_context_loader or bob_daily_bank_context_loader

    @staticmethod
    def _load_missing_tax_accounts(erp: Any, rules: list[dict[str, Any]], account_catalog: dict[int, dict[str, Any]]) -> None:
        tax_account_ids = {
            int((rule.get("target") or {}).get("tax_account_id") or 0)
            for rule in rules
            if int((rule.get("target") or {}).get("tax_account_id") or 0) > 0
        }
        missing = sorted(account_id for account_id in tax_account_ids if account_id not in account_catalog)
        if not missing:
            return
        rows = erp.execute_kw(
            "account.account",
            "search_read",
            [[["id", "in", missing]]],
            {"fields": ["id", "code", "name"], "limit": len(missing)},
        )
        for row in rows or []:
            if row.get("id"):
                account_catalog[int(row["id"])] = dict(row)

    def _rebuild_document_entries(
        self,
        db: Session,
        *,
        organization_id: int,
        document,
        journal_id: int,
        company_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        source_path = self._documents.resolve_tenant_path(document, organization_id)
        source_bytes = source_path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        transactions = parse_file(str(source_path))
        if not transactions:
            raise HTTPException(status_code=422, detail="No bank transactions were found in the source statement.")
        _connection, erp = self._erp_resolver.resolve(db, organization_id)
        journal, rules, account_catalog = self._bob_context_loader.load(
            db, organization_id, erp, journal_id=journal_id, company_id=company_id
        )
        self._load_missing_tax_accounts(erp, rules, account_catalog)
        try:
            entries = self._builder.build(
                transactions, rules=rules, journal=journal, account_catalog=account_catalog
            )
        except DailyBankEntryBuildError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        active_versions = [
            {
                "rule_id": int(rule["rule_id"]),
                "version_id": int(rule["version_id"]),
                "version_number": int(rule["version_number"]),
                "fingerprint": str(rule.get("fingerprint") or ""),
                "tax_id": int((rule.get("target") or {}).get("tax_id") or 0) or None,
            }
            for rule in rules
        ]
        context = {
            "journal_id": journal.journal_id,
            "journal_name": journal.journal_name,
            "journal_code": journal.journal_code,
            "bank_account_id": journal.bank_account_id,
            "bank_account_code": journal.bank_account_code,
            "bank_account_name": journal.bank_account_name,
            "company_id": journal.company_id,
            "rule_count": len(rules),
            "rule_source": "bob_bank_rules",
            "tax_handling": "approved_rule_tax_included_split",
            "active_rule_versions": active_versions,
        }
        return entries, context, source_hash


bob_daily_bank_review_service = BOBRulesDailyBankReviewService()
