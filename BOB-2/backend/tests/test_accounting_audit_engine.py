from __future__ import annotations

from app.services.accounting_audit_engine import AccountingAuditEngine
from app.services.daily_bank_entry_builder import BankJournalContext, DailyBankEntryBuilder


JOURNAL = BankJournalContext(
    journal_id=10,
    journal_name="Riyadh Bank",
    journal_code="BNK1",
    bank_account_id=100,
    bank_account_code="101001",
    bank_account_name="Riyadh Bank",
    company_id=1,
)

ACCOUNTS = {
    100: {"id": 100, "code": "101001", "name": "Riyadh Bank"},
    200: {"id": 200, "code": "400051", "name": "Other Bank Charges"},
}


def matched_rule(txn, rules):
    return {
        "suggested_account_id": 200,
        "suggested_account_label": "Other Bank Charges",
        "confidence": 1.0,
        "source": "bob_bank_rule",
        "source_priority": "bob_rule_priority",
        "resolution_mode": "strict_bob_rule",
        "bank_rule_id": 77,
        "bank_rule_version_id": 771,
        "bank_rule_version": 3,
        "bank_rule_fingerprint": "a" * 64,
        "bank_rule_name": "Fees",
        "reason": "Matched approved BOB rule Fees v3",
        "needs_review": False,
    }


def clean_entry():
    builder = DailyBankEntryBuilder(rule_matcher=matched_rule)
    return builder.build(
        [{"date": "2026-08-10", "description": "INSTANT PAYMENT FEES", "amount": "-5.00", "row_number": 4}],
        rules=[{"rule_id": 77}],
        journal=JOURNAL,
        account_catalog=ACCOUNTS,
    )[0]


def source_document():
    return {"document_id": 12, "filename": "bank.xls", "sha256": "a" * 64}


def codes(result):
    return {finding["code"] for finding in result["findings"]}


def test_clean_rule_backed_entry_passes_core_audit_but_still_requires_human_approval():
    entry = clean_entry()
    result = AccountingAuditEngine().audit_entry(
        entry,
        source_document=source_document(),
        source_hash_verified=True,
        current_entry_hash=entry["entry_hash"],
    )

    assert result["blocking_count"] == 0
    assert result["warning_count"] == 0
    assert result["recommendation"] == "approve"
    assert result["safe_to_post"] is False
    assert result["human_approval_required"] is True
    assert "CORE_ASSERTIONS_PASSED" in codes(result)


def test_auditor_blocks_unresolved_counterpart_and_missing_bank_rule():
    builder = DailyBankEntryBuilder(rule_matcher=lambda txn, rules: None)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "UNKNOWN", "amount": "-50.00", "row_number": 8}],
        rules=[],
        journal=JOURNAL,
        account_catalog=ACCOUNTS,
    )[0]

    result = AccountingAuditEngine().audit_entry(
        entry,
        source_document=source_document(),
        source_hash_verified=True,
        current_entry_hash=entry["entry_hash"],
    )

    assert result["recommendation"] == "needs_revision"
    assert "UNRESOLVED_COUNTERPART_ACCOUNT" in codes(result)
    assert "NO_BOB_BANK_RULE_EVIDENCE" in codes(result)


def test_auditor_blocks_document_hash_failure_and_rule_drift():
    entry = clean_entry()
    result = AccountingAuditEngine().audit_entry(
        entry,
        source_document=source_document(),
        source_hash_verified=False,
        current_entry_hash="different",
    )

    assert result["risk_level"] == "high"
    assert "SOURCE_HASH_MISMATCH" in codes(result)
    assert "BANK_RULE_DRIFT" in codes(result)


def test_low_confidence_rule_requires_human_attention_without_silent_account_change():
    def low_confidence(txn, rules):
        payload = matched_rule(txn, rules)
        payload["confidence"] = 0.55
        payload["needs_review"] = True
        return payload

    builder = DailyBankEntryBuilder(rule_matcher=low_confidence)
    entry = builder.build(
        [{"date": "2026-08-10", "description": "POSSIBLE FEE", "amount": "-5.00", "row_number": 10}],
        rules=[{"rule_id": 77}],
        journal=JOURNAL,
        account_catalog=ACCOUNTS,
    )[0]

    result = AccountingAuditEngine().audit_entry(
        entry,
        source_document=source_document(),
        source_hash_verified=True,
        current_entry_hash=entry["entry_hash"],
    )

    assert result["blocking_count"] == 0
    assert result["warning_count"] == 1
    assert result["recommendation"] == "human_review"
    assert "LOW_RULE_CONFIDENCE" in codes(result)
