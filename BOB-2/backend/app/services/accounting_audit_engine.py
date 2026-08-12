"""Explainable, fail-closed audit checks for daily bank review packages.

The engine performs deterministic accounting assertions only. It cannot post, approve,
or mutate ERP data. Every finding includes evidence and a recommended human action.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

from app.core.money import MONEY_ZERO, MoneyValidationError, money_to_str, parse_money, validate_balanced_lines


@dataclass(frozen=True, slots=True)
class AccountingAuditEngine:
    low_confidence_threshold: float = 0.70

    @staticmethod
    def _finding(
        severity: str,
        code: str,
        title: str,
        reason: str,
        evidence: Mapping[str, Any] | None = None,
        suggested_action: str = "Review the evidence before approval.",
        *,
        source_row: int | None = None,
    ) -> dict[str, Any]:
        return {
            "severity": severity,
            "code": code,
            "title": title,
            "reason": reason,
            "evidence": dict(evidence or {}),
            "suggested_action": suggested_action,
            "source_row": source_row,
        }

    def audit_entry(
        self,
        entry: Mapping[str, Any],
        *,
        source_document: Mapping[str, Any],
        source_hash_verified: bool,
        current_entry_hash: str | None = None,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        lines = [dict(line) for line in entry.get("lines") or []]
        entry_date = str(entry.get("entry_date") or "")

        if not source_document.get("document_id") or not source_document.get("sha256"):
            findings.append(self._finding(
                "error",
                "SOURCE_DOCUMENT_MISSING",
                "Source bank statement evidence is incomplete",
                "The audit package must preserve the source document identifier and cryptographic hash.",
                source_document,
                "Return the entry to accounting and rebuild the review package from the original statement.",
            ))
        elif not source_hash_verified:
            findings.append(self._finding(
                "error",
                "SOURCE_HASH_MISMATCH",
                "Source document integrity check failed",
                "The persisted bank statement no longer matches the hash sealed into the review package.",
                {"expected_sha256": source_document.get("sha256")},
                "Stop review and investigate document integrity before any approval.",
            ))

        submitted_hash = str(entry.get("entry_hash") or "")
        if current_entry_hash and submitted_hash and current_entry_hash != submitted_hash:
            findings.append(self._finding(
                "error",
                "BANK_RULE_DRIFT",
                "Current BOB Bank Rules produce a different entry",
                "The accounting proposal changed when rebuilt from the same source statement using the currently approved BOB Bank Rule versions and current Odoo reference catalogue.",
                {"submitted_entry_hash": submitted_hash, "current_entry_hash": current_entry_hash},
                "Return the entry for regeneration using the current approved BOB Bank Rule versions.",
            ))

        if not lines:
            findings.append(self._finding(
                "error",
                "NO_JOURNAL_LINES",
                "Journal entry contains no lines",
                "A daily bank journal entry cannot be audited without detailed debit and credit lines.",
                suggested_action="Return the entry to accounting for regeneration.",
            ))
        else:
            try:
                debit_total, credit_total = validate_balanced_lines(lines)
            except MoneyValidationError as exc:
                findings.append(self._finding(
                    "error",
                    "UNBALANCED_ENTRY",
                    "Journal entry is not a valid balanced double entry",
                    str(exc),
                    {"declared_debit": entry.get("total_debit"), "declared_credit": entry.get("total_credit")},
                    "Correct the journal lines before approval.",
                ))
            else:
                if money_to_str(debit_total) != str(entry.get("total_debit") or "") or money_to_str(credit_total) != str(entry.get("total_credit") or ""):
                    findings.append(self._finding(
                        "error",
                        "TOTALS_MISMATCH",
                        "Calculated totals do not match the sealed entry totals",
                        "The line-level debit/credit totals differ from the totals recorded in the review package.",
                        {
                            "calculated_debit": money_to_str(debit_total),
                            "calculated_credit": money_to_str(credit_total),
                            "declared_debit": entry.get("total_debit"),
                            "declared_credit": entry.get("total_credit"),
                        },
                        "Return the entry to accounting for a fresh server-side rebuild.",
                    ))

        dates = {str(line.get("source_date") or "") for line in lines if line.get("source_date")}
        if entry_date and any(date != entry_date for date in dates):
            findings.append(self._finding(
                "error",
                "CROSS_DAY_LINES",
                "The daily entry contains transactions from another date",
                "One journal entry must contain only bank transactions belonging to its own calendar day.",
                {"entry_date": entry_date, "source_dates": sorted(dates)},
                "Split the transactions into one journal entry per date.",
            ))

        by_transaction: dict[str, list[dict[str, Any]]] = defaultdict(list)
        missing_keys = 0
        for line in lines:
            key = str(line.get("transaction_key") or "")
            if not key:
                missing_keys += 1
                continue
            by_transaction[key].append(line)
        if missing_keys:
            findings.append(self._finding(
                "error",
                "MISSING_TRACE_KEY",
                "One or more lines cannot be traced to a bank transaction",
                "Every journal line must retain a transaction key derived from the source bank row.",
                {"line_count_without_key": missing_keys},
                "Regenerate the entry from the original bank statement.",
            ))

        source_rows = [
            (str(line.get("transaction_key") or ""), line.get("source_row"))
            for line in lines
            if line.get("role") == "bank"
        ]
        duplicate_sources = [item for item, count in Counter(source_rows).items() if count > 1]
        if duplicate_sources:
            findings.append(self._finding(
                "error",
                "DUPLICATE_BANK_TRANSACTION",
                "A bank transaction appears more than once in the daily entry",
                "Duplicate source transaction keys/rows can overstate the journal entry.",
                {"duplicates": duplicate_sources[:20]},
                "Remove duplicates and regenerate the daily entry.",
            ))

        expected_bank_account_id = entry.get("bank_account_id")
        for key, tx_lines in by_transaction.items():
            roles = Counter(str(line.get("role") or "") for line in tx_lines)
            source_row = next((line.get("source_row") for line in tx_lines if line.get("source_row") is not None), None)
            if len(tx_lines) != 2 or roles.get("bank") != 1 or roles.get("counterpart") != 1:
                findings.append(self._finding(
                    "error",
                    "INCOMPLETE_DOUBLE_ENTRY_PAIR",
                    "A bank transaction is not represented by exactly one bank and one counterpart line",
                    "Each source transaction must remain individually traceable while the day is grouped into one journal entry.",
                    {"transaction_key": key, "line_count": len(tx_lines), "roles": dict(roles)},
                    "Regenerate this transaction pair before approval.",
                    source_row=source_row,
                ))
                continue

            bank_line = next(line for line in tx_lines if line.get("role") == "bank")
            counterpart = next(line for line in tx_lines if line.get("role") == "counterpart")

            if expected_bank_account_id and bank_line.get("account_id") != expected_bank_account_id:
                findings.append(self._finding(
                    "error",
                    "BANK_ACCOUNT_MISMATCH",
                    "Bank-side line uses an account different from the selected Odoo bank journal",
                    "The liquidity account must come directly from the active Odoo bank journal.",
                    {
                        "expected_account_id": expected_bank_account_id,
                        "actual_account_id": bank_line.get("account_id"),
                        "account_code": bank_line.get("account_code"),
                    },
                    "Return the entry and rebuild it from the selected Odoo bank journal.",
                    source_row=source_row,
                ))

            if not counterpart.get("account_id") or not counterpart.get("account_code"):
                findings.append(self._finding(
                    "error",
                    "UNRESOLVED_COUNTERPART_ACCOUNT",
                    "Counterpart account is unresolved",
                    "No exact Odoo account could be proven from an active approved BOB Bank Rule. The system deliberately did not invent a fallback account.",
                    {
                        "description": counterpart.get("source_description"),
                        "bank_rule_name": counterpart.get("bank_rule_name"),
                    },
                    "Create or correct the BOB Bank Rule, approve the new version, then regenerate the entry.",
                    source_row=source_row,
                ))

            if counterpart.get("evidence_source") != "bob_bank_rule" or not counterpart.get("bank_rule_id") or not counterpart.get("bank_rule_version_id"):
                findings.append(self._finding(
                    "error",
                    "NO_BOB_BANK_RULE_EVIDENCE",
                    "Counterpart line is not supported by an approved BOB Bank Rule version",
                    "The daily bank workflow requires a versioned BOB rule and a valid Odoo target account before a line can become posting-ready.",
                    {
                        "evidence_source": counterpart.get("evidence_source"),
                        "bank_rule_id": counterpart.get("bank_rule_id"),
                        "bank_rule_version_id": counterpart.get("bank_rule_version_id"),
                    },
                    "Configure and approve the appropriate BOB Bank Rule version, then resubmit the entry.",
                    source_row=source_row,
                ))

            confidence = float(counterpart.get("confidence") or 0.0)
            if confidence < self.low_confidence_threshold:
                findings.append(self._finding(
                    "warning",
                    "LOW_RULE_CONFIDENCE",
                    "Bank Rule match needs human attention",
                    "The rule resolution is below the configured confidence threshold.",
                    {
                        "confidence": round(confidence, 4),
                        "threshold": self.low_confidence_threshold,
                        "bank_rule_name": counterpart.get("bank_rule_name"),
                        "bank_rule_version": counterpart.get("bank_rule_version"),
                        "description": counterpart.get("source_description"),
                    },
                    "Review the transaction and rule evidence before approval.",
                    source_row=source_row,
                ))

            try:
                source_amount = abs(parse_money(counterpart.get("source_amount")))
                bank_value = parse_money(bank_line.get("debit")) + parse_money(bank_line.get("credit"))
                counterpart_value = parse_money(counterpart.get("debit")) + parse_money(counterpart.get("credit"))
            except MoneyValidationError as exc:
                findings.append(self._finding(
                    "error",
                    "INVALID_TRANSACTION_AMOUNT",
                    "Transaction amount cannot be validated",
                    str(exc),
                    {"transaction_key": key},
                    "Regenerate the entry from the source statement.",
                    source_row=source_row,
                ))
            else:
                if source_amount <= MONEY_ZERO or bank_value != source_amount or counterpart_value != source_amount:
                    findings.append(self._finding(
                        "error",
                        "SOURCE_AMOUNT_MISMATCH",
                        "Journal line amount differs from the source bank transaction",
                        "The source amount must be preserved exactly on both sides of the double entry.",
                        {
                            "source_amount": money_to_str(source_amount),
                            "bank_line_amount": money_to_str(bank_value),
                            "counterpart_amount": money_to_str(counterpart_value),
                        },
                        "Return the entry for regeneration; do not manually override the amount.",
                        source_row=source_row,
                    ))

        error_count = sum(1 for finding in findings if finding["severity"] == "error")
        warning_count = sum(1 for finding in findings if finding["severity"] == "warning")
        if error_count:
            recommendation = "needs_revision"
            risk_level = "high"
        elif warning_count:
            recommendation = "human_review"
            risk_level = "medium"
        else:
            recommendation = "approve"
            risk_level = "low"
            findings.append(self._finding(
                "info",
                "CORE_ASSERTIONS_PASSED",
                "Core accounting and traceability checks passed",
                "The entry is balanced, source-linked, supported by an approved versioned BOB Bank Rule, and references live Odoo accounting metadata. Human approval is still required before any ERP posting.",
                {
                    "entry_date": entry_date,
                    "transaction_count": entry.get("transaction_count"),
                    "total_debit": entry.get("total_debit"),
                    "total_credit": entry.get("total_credit"),
                },
                "Perform the final human review of business purpose/supporting evidence, then approve or return the package.",
            ))

        return {
            "risk_level": risk_level,
            "recommendation": recommendation,
            "blocking_count": error_count,
            "warning_count": warning_count,
            "finding_count": len(findings),
            "checks_passed": error_count == 0,
            "safe_to_post": False,
            "human_approval_required": True,
            "findings": findings,
        }
