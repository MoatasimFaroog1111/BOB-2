"""Tax-aware adapter for the immutable daily bank accounting auditor.

The generic auditor deliberately requires one bank + one counterpart line per source
transaction. Tax-aware BOB rules legitimately add a third tax line. This adapter
validates that tax split first, then presents an equivalent synthetic counterpart to
the generic auditor so all existing traceability, confidence, source-hash, and account
checks remain active without weakening the general invariant.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping

from app.core.money import MoneyValidationError, money_to_str, parse_money
from app.services.accounting_audit_engine import AccountingAuditEngine


class TaxAwareAccountingAuditEngine(AccountingAuditEngine):
    @staticmethod
    def _tax_finding(
        code: str,
        title: str,
        reason: str,
        evidence: dict[str, Any],
        source_row: int | None,
    ) -> dict[str, Any]:
        return {
            "severity": "error",
            "code": code,
            "title": title,
            "reason": reason,
            "evidence": evidence,
            "suggested_action": "Correct the approved Bank Rule tax configuration and regenerate the review entry.",
            "source_row": source_row,
        }

    @staticmethod
    def _recalculate(summary: dict[str, Any], extra_findings: list[dict[str, Any]]) -> dict[str, Any]:
        findings = [
            finding
            for finding in list(summary.get("findings") or [])
            if finding.get("code") != "CORE_ASSERTIONS_PASSED"
        ]
        findings.extend(extra_findings)
        error_count = sum(1 for finding in findings if finding.get("severity") == "error")
        warning_count = sum(1 for finding in findings if finding.get("severity") == "warning")
        summary["findings"] = findings
        summary["blocking_count"] = error_count
        summary["warning_count"] = warning_count
        summary["finding_count"] = len(findings)
        summary["checks_passed"] = error_count == 0
        summary["safe_to_post"] = False
        summary["human_approval_required"] = True
        if error_count:
            summary["recommendation"] = "needs_revision"
            summary["risk_level"] = "high"
        elif warning_count:
            summary["recommendation"] = "human_review"
            summary["risk_level"] = "medium"
        else:
            summary["recommendation"] = "approve"
            summary["risk_level"] = "low"
            findings.append({
                "severity": "info",
                "code": "CORE_ASSERTIONS_PASSED",
                "title": "Core accounting, tax, and traceability checks passed",
                "reason": "The entry is balanced, the tax split reconciles to the source bank amount, and the accounting proposal remains supported by approved BOB Bank Rule evidence.",
                "evidence": {},
                "suggested_action": "Perform final human business-purpose review before approval.",
                "source_row": None,
            })
            summary["finding_count"] = len(findings)
        return summary

    def audit_entry(
        self,
        entry: Mapping[str, Any],
        *,
        source_document: Mapping[str, Any],
        source_hash_verified: bool,
        current_entry_hash: str | None = None,
    ) -> dict[str, Any]:
        original_lines = [deepcopy(line) for line in entry.get("lines") or []]
        has_tax_line = any(line.get("role") == "tax" for line in original_lines)
        has_failed_tax = any(line.get("tax_resolution_failed") for line in original_lines)
        if not has_tax_line and not has_failed_tax:
            return super().audit_entry(
                entry,
                source_document=source_document,
                source_hash_verified=source_hash_verified,
                current_entry_hash=current_entry_hash,
            )

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for line in original_lines:
            groups[str(line.get("transaction_key") or "")].append(line)

        synthetic_lines: list[dict[str, Any]] = []
        tax_findings: list[dict[str, Any]] = []
        for key, lines in groups.items():
            source_row = next((line.get("source_row") for line in lines if line.get("source_row") is not None), None)
            failed_lines = [line for line in lines if line.get("tax_resolution_failed")]
            if failed_lines:
                first = failed_lines[0]
                tax_findings.append(self._tax_finding(
                    "TAX_RESOLUTION_FAILED",
                    "Approved Bank Rule tax could not be resolved safely",
                    str(first.get("tax_error") or "The configured tax could not be resolved against current Odoo metadata."),
                    {
                        "transaction_key": key,
                        "tax_id": first.get("tax_id"),
                        "line_count": len(lines),
                    },
                    source_row,
                ))
                synthetic_lines.extend(lines)
                continue

            tax_lines = [line for line in lines if line.get("role") == "tax"]
            if not tax_lines:
                synthetic_lines.extend(lines)
                continue
            bank_lines = [line for line in lines if line.get("role") == "bank"]
            counterparts = [line for line in lines if line.get("role") == "counterpart"]
            if len(lines) != 3 or len(bank_lines) != 1 or len(counterparts) != 1 or len(tax_lines) != 1:
                tax_findings.append(self._tax_finding(
                    "INVALID_TAX_LINE_SET",
                    "Tax-aware bank transaction has an invalid line set",
                    "A taxed source movement must contain exactly one bank line, one base counterpart line, and one tax line.",
                    {"transaction_key": key, "roles": [line.get("role") for line in lines]},
                    source_row,
                ))
                synthetic_lines.extend(lines)
                continue

            bank_line, counterpart, tax_line = bank_lines[0], counterparts[0], tax_lines[0]
            if not tax_line.get("account_id") or not tax_line.get("account_code") or not tax_line.get("tax_id"):
                tax_findings.append(self._tax_finding(
                    "UNRESOLVED_TAX_ACCOUNT",
                    "Tax line is not backed by a resolved Odoo tax account",
                    "The approved rule must resolve both an Odoo tax and its repartition posting account.",
                    {"transaction_key": key, "tax_id": tax_line.get("tax_id"), "account_id": tax_line.get("account_id")},
                    source_row,
                ))
                synthetic_lines.extend(lines)
                continue

            try:
                source_amount = abs(parse_money(counterpart.get("source_amount")))
                bank_amount = parse_money(bank_line.get("debit")) + parse_money(bank_line.get("credit"))
                base_amount = parse_money(counterpart.get("debit")) + parse_money(counterpart.get("credit"))
                tax_amount = parse_money(tax_line.get("debit")) + parse_money(tax_line.get("credit"))
            except MoneyValidationError as exc:
                tax_findings.append(self._tax_finding(
                    "INVALID_TAX_SPLIT_AMOUNT",
                    "Tax split contains an invalid monetary value",
                    str(exc),
                    {"transaction_key": key},
                    source_row,
                ))
                synthetic_lines.extend(lines)
                continue

            if source_amount != bank_amount or source_amount != base_amount + tax_amount:
                tax_findings.append(self._tax_finding(
                    "TAX_SPLIT_SOURCE_MISMATCH",
                    "Base plus tax does not reconcile to the bank movement",
                    "The tax-aware split must preserve the exact source cash amount: base + tax = bank gross.",
                    {
                        "transaction_key": key,
                        "source_amount": money_to_str(source_amount),
                        "bank_amount": money_to_str(bank_amount),
                        "base_amount": money_to_str(base_amount),
                        "tax_amount": money_to_str(tax_amount),
                    },
                    source_row,
                ))
                synthetic_lines.extend(lines)
                continue

            synthetic_counterpart = deepcopy(counterpart)
            synthetic_counterpart["debit"] = money_to_str(
                parse_money(counterpart.get("debit")) + parse_money(tax_line.get("debit"))
            )
            synthetic_counterpart["credit"] = money_to_str(
                parse_money(counterpart.get("credit")) + parse_money(tax_line.get("credit"))
            )
            synthetic_counterpart["tax_audit_normalized"] = True
            synthetic_lines.extend([bank_line, synthetic_counterpart])

        normalized_entry = dict(entry)
        normalized_entry["lines"] = synthetic_lines
        normalized_entry["line_count"] = len(synthetic_lines)
        summary = super().audit_entry(
            normalized_entry,
            source_document=source_document,
            source_hash_verified=source_hash_verified,
            current_entry_hash=current_entry_hash,
        )
        return self._recalculate(summary, tax_findings)


bank_rule_tax_auditor = TaxAwareAccountingAuditEngine()
