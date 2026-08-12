"""Context loader for daily bank accounting.

BOB supplies the executable Bank Rules. Odoo is queried only for the selected bank
journal and the referenced account metadata, preserving a clean ownership boundary.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.bank_rules_service import BankRulesService, bank_rules_service
from app.services.daily_bank_entry_builder import BankJournalContext
from app.services.tenant_erp_service import OdooReferenceValidator, odoo_reference_validator


class BOBDailyBankContextLoader:
    def __init__(
        self,
        *,
        rules_service: BankRulesService | None = None,
        reference_validator: OdooReferenceValidator | None = None,
    ) -> None:
        self._rules = rules_service or bank_rules_service
        self._references = reference_validator or odoo_reference_validator

    def load(
        self,
        db: Session,
        organization_id: int,
        erp: Any,
        *,
        journal_id: int,
        company_id: int | None = None,
    ) -> tuple[BankJournalContext, list[dict[str, Any]], dict[int, dict[str, Any]]]:
        selected = self._references.bank_journal(erp, journal_id, company_id)
        bank_account_id = int(selected.get("account_id") or 0)
        selected_company_id = int(selected.get("company_id") or 0) or company_id

        rules = self._rules.active_rules(
            db,
            organization_id=organization_id,
            journal_id=int(journal_id),
            company_id=selected_company_id,
        )
        if not rules:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No active BOB Bank Rules are configured for this bank journal. "
                    "Import the existing Odoo rules as drafts or create BOB rules, review them, and approve them before preparing bank entries."
                ),
            )

        account_ids = {bank_account_id}
        for rule in rules:
            target = rule.get("target") or {}
            account_id = int(target.get("account_id") or 0)
            if account_id > 0:
                account_ids.add(account_id)
        rows = erp.execute_kw(
            "account.account",
            "search_read",
            [[["id", "in", sorted(account_ids)]]],
            {"fields": ["id", "code", "name"], "limit": max(len(account_ids), 1)},
        )
        account_catalog = {int(row["id"]): dict(row) for row in rows if row.get("id")}
        bank_account = account_catalog.get(bank_account_id) or {}
        bank_code = str(bank_account.get("code") or selected.get("account_code") or "").strip()
        bank_name = str(bank_account.get("name") or selected.get("account_name") or "").strip()
        if not bank_code or not bank_name:
            raise HTTPException(status_code=422, detail="Odoo bank account code/name could not be resolved.")

        journal = BankJournalContext(
            journal_id=int(selected["journal_id"]),
            journal_name=str(selected.get("journal_name") or ""),
            journal_code=str(selected.get("journal_code") or ""),
            bank_account_id=bank_account_id,
            bank_account_code=bank_code,
            bank_account_name=bank_name,
            company_id=selected_company_id,
        )
        return journal, rules, account_catalog


bob_daily_bank_context_loader = BOBDailyBankContextLoader()
