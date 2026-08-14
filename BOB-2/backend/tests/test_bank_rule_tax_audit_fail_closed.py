from __future__ import annotations

from app.services.bank_rule_tax_audit import TaxAwareAccountingAuditEngine
from app.services.daily_bank_entry_builder import BankJournalContext
from app.services.daily_bank_review_bob_rules import BOBTaxAwareDailyBankEntryBuilder


JOURNAL = BankJournalContext(
    journal_id=10,
    journal_name="Riyadh Bank",
    journal_code="BNK1",
    bank_account_id=100,
    bank_account_code="101001",
    bank_account_name="Riyadh Bank",
    company_id=1,
)


def _rule_matcher(_txn, _rules):
    return {
        "suggested_account_id": 200,
        "suggested_account_label": "Other Bank Charges",
        "suggested_partner_id": None,
        "suggested_partner_label": "",
        "suggested_analytic_account_id": None,
        "suggested_analytic_account_label": "",
        "confidence": 1.0,
        "source": "bob_bank_rule",
        "source_priority": "bob_rule_priority",
        "resolution_mode": "strict_bob_rule",
        "bank_rule_id": 77,
        "bank_rule_version_id": 771,
        "bank_rule_version": 1,
        "bank_rule_fingerprint": "a" * 64,
        "bank_rule_name": "Fees",
        "reason": "Matched approved BOB rule Fees v1",
        "needs_review": False,
    }


def test_failed_tax_resolution_creates_blocking_audit_finding():
    builder = BOBTaxAwareDailyBankEntryBuilder(rule_matcher=_rule_matcher)
    rule = {
        "rule_id": 77,
        "target": {
            "account_id": 200,
            "account_code": "400051",
            "account_name": "Other Bank Charges",
            "tax_id": 15,
            "tax_name": "VAT 15% Purchases",
            "tax_rate": 15.0,
            "tax_amount_type": "percent",
            "tax_type_use": "purchase",
            "tax_account_id": 300,
            "tax_account_code": "102020",
            "tax_account_name": "VAT Input",
            "tax_amount_mode": "included_in_bank_amount",
        },
    }
    accounts_without_tax = {
        100: {"id": 100, "code": "101001", "name": "Riyadh Bank"},
        200: {"id": 200, "code": "400051", "name": "Other Bank Charges"},
    }
    entry = builder.build(
        [{"date": "2026-08-10", "description": "BANK FEE VAT", "amount": "-115.00", "row_number": 10}],
        rules=[rule],
        journal=JOURNAL,
        account_catalog=accounts_without_tax,
    )[0]

    assert any(line.get("tax_resolution_failed") for line in entry["lines"])
    audit = TaxAwareAccountingAuditEngine().audit_entry(
        entry,
        source_document={"document_id": 1, "sha256": "a" * 64},
        source_hash_verified=True,
    )
    codes = {finding["code"] for finding in audit["findings"]}
    assert "TAX_RESOLUTION_FAILED" in codes
    assert audit["blocking_count"] >= 1
    assert audit["recommendation"] == "needs_revision"
