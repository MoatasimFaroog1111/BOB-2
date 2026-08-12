"""BOB Bank Rules implementation of the existing daily review workflow.

The established review/audit lifecycle stays closed for modification; this subclass only
replaces the rule/reference context source, following Open/Closed and dependency
inversion principles.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.erp.bank_reconciliation import parse_file
from app.services.daily_bank_context import BOBDailyBankContextLoader, bob_daily_bank_context_loader
from app.services.daily_bank_entry_builder import DailyBankEntryBuildError
from app.services.daily_bank_review_service import DailyBankReviewService


class BOBRulesDailyBankReviewService(DailyBankReviewService):
    def __init__(
        self,
        *,
        bob_context_loader: BOBDailyBankContextLoader | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._bob_context_loader = bob_context_loader or bob_daily_bank_context_loader

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
            db,
            organization_id,
            erp,
            journal_id=journal_id,
            company_id=company_id,
        )
        try:
            entries = self._builder.build(
                transactions,
                rules=rules,
                journal=journal,
                account_catalog=account_catalog,
            )
        except DailyBankEntryBuildError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        active_versions = [
            {
                "rule_id": int(rule["rule_id"]),
                "version_id": int(rule["version_id"]),
                "version_number": int(rule["version_number"]),
                "fingerprint": str(rule.get("fingerprint") or ""),
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
            "active_rule_versions": active_versions,
        }
        return entries, context, source_hash


bob_daily_bank_review_service = BOBRulesDailyBankReviewService()
