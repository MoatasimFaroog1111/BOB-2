"""Build review-only daily bank journal entries from Odoo bank rules.

This component contains accounting business logic only. It does not know about HTTP,
databases, files, or Odoo transports. Odoo remains the source of truth because callers
must provide the selected bank journal, rule set, and account catalogue read from ERP.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from app.core.money import MONEY_ZERO, money_to_str, parse_money, validate_balanced_lines
from app.erp.bank_rule_resolver import resolve_by_odoo_bank_rule


BankRuleMatcher = Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any] | None]


class DailyBankEntryBuildError(ValueError):
    """Raised when a bank statement cannot be represented safely for review."""


@dataclass(frozen=True, slots=True)
class BankJournalContext:
    journal_id: int
    journal_name: str
    journal_code: str
    bank_account_id: int
    bank_account_code: str
    bank_account_name: str
    company_id: int | None = None


@dataclass(frozen=True, slots=True)
class DailyBankEntryBuilder:
    """Convert statement transactions into one detailed balanced entry per day."""

    rule_matcher: BankRuleMatcher = resolve_by_odoo_bank_rule
    low_confidence_threshold: float = 0.70
    max_transactions: int = 10_000

    @staticmethod
    def _transaction_payload(transaction: Any) -> dict[str, Any]:
        if hasattr(transaction, "model_dump"):
            raw = transaction.model_dump()
        elif isinstance(transaction, Mapping):
            raw = dict(transaction)
        else:
            raise DailyBankEntryBuildError("Unsupported bank transaction shape")

        date_value = str(raw.get("date") or "").strip()
        description = str(raw.get("description") or "").strip()
        if not date_value:
            raise DailyBankEntryBuildError("Bank transaction date is required")
        if not description:
            raise DailyBankEntryBuildError("Bank transaction description is required")

        amount = parse_money(raw.get("amount"), field_name="bank_transaction.amount")
        if amount == MONEY_ZERO:
            raise DailyBankEntryBuildError("Zero-value bank transactions cannot create journal lines")

        row_number = raw.get("row_number")
        try:
            normalized_row = int(row_number) if row_number is not None else 0
        except (TypeError, ValueError):
            normalized_row = 0

        raw["date"] = date_value
        raw["description"] = description
        raw["amount"] = money_to_str(amount)
        raw["row_number"] = normalized_row
        return raw

    @staticmethod
    def _transaction_key(transaction: Mapping[str, Any]) -> str:
        canonical = json.dumps(
            {
                "date": transaction.get("date"),
                "row_number": transaction.get("row_number"),
                "description": transaction.get("description"),
                "amount": transaction.get("amount"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _entry_hash(entry_date: str, lines: list[dict[str, Any]]) -> str:
        canonical = json.dumps(
            {"entry_date": entry_date, "lines": lines},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _account_details(
        account_id: int | None,
        account_catalog: Mapping[int, Mapping[str, Any]],
        fallback_label: str = "",
    ) -> tuple[str, str]:
        if not account_id:
            return "", ""
        row = account_catalog.get(int(account_id)) or {}
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or fallback_label or "").strip()
        return code, name

    def _build_transaction_lines(
        self,
        transaction: dict[str, Any],
        *,
        rules: list[dict[str, Any]],
        journal: BankJournalContext,
        account_catalog: Mapping[int, Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        amount = parse_money(transaction["amount"], field_name="bank_transaction.amount")
        magnitude = abs(amount)
        tx_key = self._transaction_key(transaction)

        rule_input = dict(transaction)
        rule_input["amount"] = float(amount)
        suggestion = self.rule_matcher(rule_input, rules)

        counterpart_account_id: int | None = None
        counterpart_code = ""
        counterpart_name = ""
        partner_id: int | None = None
        partner_name = ""
        analytic_account_id: int | None = None
        analytic_account_name = ""
        confidence = 0.0
        bank_rule_id: int | None = None
        bank_rule_name = ""
        reason = "No Odoo Bank Rule candidate could be supported by the available statement evidence."
        evidence_source = "unresolved"
        source_priority = "unresolved"
        resolution_mode = "unresolved"
        needs_review = True

        if suggestion and suggestion.get("suggested_account_id"):
            counterpart_account_id = int(suggestion["suggested_account_id"])
            counterpart_code, counterpart_name = self._account_details(
                counterpart_account_id,
                account_catalog,
                str(suggestion.get("suggested_account_label") or ""),
            )
            if counterpart_code and counterpart_name:
                partner_id = int(suggestion["suggested_partner_id"]) if suggestion.get("suggested_partner_id") else None
                partner_name = str(suggestion.get("suggested_partner_label") or "")
                analytic_account_id = (
                    int(suggestion["suggested_analytic_account_id"])
                    if suggestion.get("suggested_analytic_account_id")
                    else None
                )
                analytic_account_name = str(suggestion.get("suggested_analytic_account_label") or "")
                confidence = float(suggestion.get("confidence") or 0.0)
                bank_rule_id = int(suggestion["bank_rule_id"]) if suggestion.get("bank_rule_id") else None
                bank_rule_name = str(suggestion.get("bank_rule_name") or "")
                reason = str(suggestion.get("reason") or "Matched Odoo Bank Rule")
                evidence_source = str(suggestion.get("source") or "odoo_bank_reconciliation_rule")
                source_priority = str(suggestion.get("source_priority") or "bank_rule")
                resolution_mode = str(suggestion.get("resolution_mode") or "review_only_odoo_rule_suggestion")
                needs_review = bool(suggestion.get("needs_review")) or confidence < self.low_confidence_threshold
            else:
                counterpart_account_id = None
                reason = "Matched Odoo rule account is missing exact code/name metadata from ERP."

        bank_debit = magnitude if amount > MONEY_ZERO else MONEY_ZERO
        bank_credit = magnitude if amount < MONEY_ZERO else MONEY_ZERO
        counterpart_debit = bank_credit
        counterpart_credit = bank_debit

        shared_evidence = {
            "transaction_key": tx_key,
            "source_row": transaction.get("row_number"),
            "source_date": transaction.get("date"),
            "source_description": transaction.get("description"),
            "source_amount": money_to_str(amount),
            "bank_rule_id": bank_rule_id,
            "bank_rule_name": bank_rule_name,
            "confidence": round(confidence, 4),
            "evidence_source": evidence_source,
            "source_priority": source_priority,
            "resolution_mode": resolution_mode,
            "reason": reason,
            "needs_review": needs_review,
        }

        bank_line = {
            **shared_evidence,
            "role": "bank",
            "account_id": journal.bank_account_id,
            "account_code": journal.bank_account_code,
            "account_name": journal.bank_account_name,
            "debit": money_to_str(bank_debit),
            "credit": money_to_str(bank_credit),
            "name": str(transaction.get("description") or "")[:255],
            "partner_id": None,
            "partner_name": "",
            "analytic_account_id": None,
            "analytic_account_name": "",
        }
        counterpart_line = {
            **shared_evidence,
            "role": "counterpart",
            "account_id": counterpart_account_id,
            "account_code": counterpart_code,
            "account_name": counterpart_name,
            "debit": money_to_str(counterpart_debit),
            "credit": money_to_str(counterpart_credit),
            "name": str(transaction.get("description") or "")[:255],
            "partner_id": partner_id,
            "partner_name": partner_name,
            "analytic_account_id": analytic_account_id,
            "analytic_account_name": analytic_account_name,
        }
        unresolved = counterpart_account_id is None or not counterpart_code or not bank_rule_id
        return [bank_line, counterpart_line], unresolved, needs_review

    def build(
        self,
        transactions: Iterable[Any],
        *,
        rules: list[dict[str, Any]],
        journal: BankJournalContext,
        account_catalog: Mapping[int, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if journal.journal_id <= 0 or journal.bank_account_id <= 0:
            raise DailyBankEntryBuildError("A valid Odoo bank journal and liquidity account are required")
        if not journal.bank_account_code or not journal.bank_account_name:
            raise DailyBankEntryBuildError("Odoo bank account code/name metadata is required")

        normalized = [self._transaction_payload(txn) for txn in transactions]
        if not normalized:
            raise DailyBankEntryBuildError("Bank statement contains no accounting transactions")
        if len(normalized) > self.max_transactions:
            raise DailyBankEntryBuildError("Bank statement exceeds the safe transaction limit")

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for transaction in normalized:
            grouped[transaction["date"]].append(transaction)

        entries: list[dict[str, Any]] = []
        for entry_date in sorted(grouped):
            lines: list[dict[str, Any]] = []
            unresolved_count = 0
            low_confidence_count = 0
            transaction_keys: set[str] = set()
            duplicate_count = 0

            for transaction in grouped[entry_date]:
                tx_lines, unresolved, needs_review = self._build_transaction_lines(
                    transaction,
                    rules=rules,
                    journal=journal,
                    account_catalog=account_catalog,
                )
                tx_key = str(tx_lines[0]["transaction_key"])
                if tx_key in transaction_keys:
                    duplicate_count += 1
                transaction_keys.add(tx_key)
                lines.extend(tx_lines)
                unresolved_count += int(unresolved)
                low_confidence_count += int(needs_review)

            total_debit, total_credit = validate_balanced_lines(lines)
            entry = {
                "entry_date": entry_date,
                "journal_id": journal.journal_id,
                "journal_name": journal.journal_name,
                "journal_code": journal.journal_code,
                "bank_account_id": journal.bank_account_id,
                "bank_account_code": journal.bank_account_code,
                "bank_account_name": journal.bank_account_name,
                "company_id": journal.company_id,
                "transaction_count": len(grouped[entry_date]),
                "line_count": len(lines),
                "total_debit": money_to_str(total_debit),
                "total_credit": money_to_str(total_credit),
                "balanced": total_debit == total_credit,
                "unresolved_count": unresolved_count,
                "low_confidence_count": low_confidence_count,
                "duplicate_count": duplicate_count,
                "ready_for_review": total_debit == total_credit and duplicate_count == 0,
                "ready_for_posting": (
                    total_debit == total_credit
                    and unresolved_count == 0
                    and low_confidence_count == 0
                    and duplicate_count == 0
                ),
                "lines": lines,
            }
            entry["entry_hash"] = self._entry_hash(entry_date, lines)
            entries.append(entry)

        return entries
