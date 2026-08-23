"""Contracts shared by bank reconciliation suggestion components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SuggestionBatchContext:
    organization_id: int
    company_id: int | None = None
    bank_journal_id: int | None = None
    bank_account_id: int | None = None
    history_limit: int = 600
    semantic_limit: int = 40
