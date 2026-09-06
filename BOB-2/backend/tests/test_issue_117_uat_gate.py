"""Issue #117 UAT evidence gate for the paid reconciliation pilot.

This test uses synthetic, non-customer data. It proves the deterministic acceptance
contract before any live non-production Odoo UAT is signed off.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.api.v1.bank_posting_v2 import (
    BankPostingLineV2,
    BankPostingRequestV2,
    build_idempotency_key,
)
from app.erp.bank_reconciliation import _run_matching, parse_csv_file


UAT_DIR = Path(__file__).resolve().parents[2] / "release" / "uat" / "issue-117"


def _expected() -> dict:
    return json.loads((UAT_DIR / "expected_results.json").read_text(encoding="utf-8"))


def test_issue_117_fixture_matches_expected_reconciliation_counts():
    expected = _expected()
    statement = parse_csv_file(str(UAT_DIR / "bank_statement.csv"))
    ledger = parse_csv_file(str(UAT_DIR / "odoo_ledger.csv"))

    result = _run_matching(statement, ledger)

    assert len(statement) == expected["statement_count"]
    assert len(ledger) == expected["ledger_count"]
    assert len(result.matched) == expected["matched_count"]
    assert len(result.statement_only) == expected["statement_only_count"]
    assert len(result.ledger_only) == expected["ledger_only_count"]

    statement_only = result.statement_only[0]
    ledger_only = result.ledger_only[0]
    assert statement_only.description == "Bank service fee"
    assert Decimal(str(statement_only.amount)) == Decimal("-57.50")
    assert ledger_only.description == "Unpresented cheque"
    assert Decimal(str(ledger_only.amount)) == Decimal("-1250.00")


def test_issue_117_exception_requires_human_review_and_balanced_proposal():
    expected = _expected()["expected_statement_only"][0]
    assert expected["required_action"] == "human_review"
    assert expected["proposed_account"] == "Bank Charges"

    debit = sum(
        Decimal(line["amount"])
        for line in expected["proposed_entry"]
        if line["side"] == "debit"
    )
    credit = sum(
        Decimal(line["amount"])
        for line in expected["proposed_entry"]
        if line["side"] == "credit"
    )
    assert debit == credit == Decimal("57.50")


def _approved_payload() -> BankPostingRequestV2:
    return BankPostingRequestV2(
        company_id=7,
        date="2026-08-03",
        ref="ISSUE-117-UAT/BANK-FEE",
        statement_ref="STMT-003",
        row_number=3,
        amount=Decimal("-57.50"),
        approval_status="approved",
        lines=[
            BankPostingLineV2(
                account_id=4100,
                debit=Decimal("57.50"),
                credit=Decimal("0.00"),
                name="Bank service fee",
            ),
            BankPostingLineV2(
                account_id=1010,
                debit=Decimal("0.00"),
                credit=Decimal("57.50"),
                name="Bank service fee",
            ),
        ],
    )


def test_issue_117_retry_builds_same_idempotency_key():
    first = build_idempotency_key(organization_id=3, company_id=7, payload=_approved_payload())
    retry = build_idempotency_key(organization_id=3, company_id=7, payload=_approved_payload())
    assert first == retry
    assert len(first) == 64


def test_issue_117_human_approval_and_duplicate_guard_precede_odoo_create():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "v1"
        / "bank_posting_v2.py"
    ).read_text(encoding="utf-8")

    approval_gate = source.index('payload.approval_status')
    duplicate_lookup = source.index('"account.move",\n            "search_read"')
    duplicate_return = source.index('"status": "duplicate_prevented"')
    create_move = source.index('erp.execute_kw("account.move", "create"')

    assert approval_gate < duplicate_lookup < duplicate_return < create_move


def test_issue_117_posting_boundary_does_not_call_action_post():
    """The UAT posting boundary creates the approved move but does not auto-post it."""

    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "v1"
        / "bank_posting_v2.py"
    ).read_text(encoding="utf-8")
    assert "action_post" not in source
