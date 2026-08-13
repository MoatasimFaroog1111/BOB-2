"""Capability contracts for the accounting-intelligence learning layer.

The learning layer depends on small read-only capabilities rather than a concrete
ERP provider.  This keeps ERP access replaceable and prevents training code from
acquiring posting privileges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AccountingReferenceCatalog:
    accounts: tuple[dict[str, Any], ...] = ()
    journals: tuple[dict[str, Any], ...] = ()
    taxes: tuple[dict[str, Any], ...] = ()
    partners: tuple[dict[str, Any], ...] = ()
    analytic_accounts: tuple[dict[str, Any], ...] = ()
    products: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class HistoricalAccountingExample:
    source_id: int
    source_reference: str
    text: str
    occurred_on: str | None
    amount: float | None
    currency: str | None
    move_type: str | None
    journal_id: int | None
    partner_id: int | None
    debit_account_ids: tuple[int, ...] = ()
    credit_account_ids: tuple[int, ...] = ()
    tax_ids: tuple[int, ...] = ()
    analytic_account_ids: tuple[int, ...] = ()
    attachment_features: tuple[str, ...] = ()
    feature_metadata: dict[str, Any] = field(default_factory=dict)


class AccountingLearningSource(Protocol):
    """Read-only source used to build accounting training examples."""

    def reference_catalog(self) -> AccountingReferenceCatalog: ...

    def historical_examples(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 1000,
        company_id: int | None = None,
    ) -> list[HistoricalAccountingExample]: ...
