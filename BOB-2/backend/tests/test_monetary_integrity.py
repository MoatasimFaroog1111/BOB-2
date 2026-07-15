"""Regression tests for fixed-point accounting amounts."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Numeric
from sqlalchemy.exc import IntegrityError

from app.core.money import (
    MONEY_MAX_ABS,
    MoneyValidationError,
    canonical_money_lines,
    money_sum,
    money_to_erp_float,
    money_to_str,
    parse_money,
    validate_balanced_lines,
)
from app.models.bank_reconciliation import BankReconciliationAuditLog
from app.models.core import AuditLog, JournalEntryRecord


def test_decimal_parsing_and_summing_never_use_binary_float_arithmetic():
    assert money_sum(["0.10", "0.20"]) == Decimal("0.30")
    assert parse_money(0.1) == Decimal("0.10")
    assert parse_money("1,234.50") == Decimal("1234.50")
    assert money_to_str(Decimal("12")) == "12.00"


@pytest.mark.parametrize("value", [None, True, "", "NaN", "Infinity", "-Infinity"])
def test_invalid_non_finite_or_non_numeric_money_is_rejected(value):
    with pytest.raises(MoneyValidationError):
        parse_money(value)


def test_range_and_fractional_scale_are_enforced():
    assert parse_money(MONEY_MAX_ABS) == MONEY_MAX_ABS
    with pytest.raises(MoneyValidationError, match="range"):
        parse_money(MONEY_MAX_ABS + Decimal("0.01"))
    with pytest.raises(MoneyValidationError, match="at most 2 decimal places"):
        parse_money("10.001", reject_excess_scale=True)


def test_balanced_lines_are_exact_and_json_safe():
    lines = [
        {"account": "1000", "debit": "0.10", "credit": "0.00"},
        {"account": "1001", "debit": "0.20", "credit": "0.00"},
        {"account": "3000", "debit": "0.00", "credit": "0.30"},
    ]
    debit, credit = validate_balanced_lines(lines)
    assert debit == credit == Decimal("0.30")
    stored = canonical_money_lines(lines)
    assert stored[0]["debit"] == "0.10"
    assert stored[2]["credit"] == "0.30"
    assert all(not isinstance(line["debit"], float) for line in stored)


def test_unbalanced_or_double_sided_lines_are_rejected():
    with pytest.raises(MoneyValidationError, match="not balanced"):
        validate_balanced_lines(
            [
                {"debit": "10.00", "credit": "0.00"},
                {"debit": "0.00", "credit": "9.99"},
            ]
        )
    with pytest.raises(MoneyValidationError, match="exactly one"):
        validate_balanced_lines(
            [
                {"debit": "10.00", "credit": "1.00"},
                {"debit": "0.00", "credit": "9.00"},
            ]
        )


def test_erp_boundary_conversion_round_trips_at_application_scale():
    external = money_to_erp_float("64083.75")
    assert isinstance(external, float)
    assert parse_money(str(external)) == Decimal("64083.75")


def test_journal_api_persists_decimal_totals_and_string_lines(client, auth_headers, db):
    response = client.post(
        "/api/v1/journal/entries",
        headers=auth_headers,
        json={
            "date": "2026-07-15",
            "reference": "DECIMAL/2026/0001",
            "memo": "Exact decimal journal",
            "lines": [
                {"account": "1000", "debit": "0.10", "credit": "0.00", "description": "A"},
                {"account": "1001", "debit": "0.20", "credit": "0.00", "description": "B"},
                {"account": "3000", "debit": "0.00", "credit": "0.30", "description": "C"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_debit"] == "0.30"
    assert body["total_credit"] == "0.30"
    assert body["lines"][0]["debit"] == "0.10"
    assert body["lines"][2]["credit"] == "0.30"

    record = db.query(JournalEntryRecord).filter_by(reference="DECIMAL/2026/0001").one()
    assert isinstance(record.total_debit, Decimal)
    assert record.total_debit == Decimal("0.30")
    assert record.total_credit == Decimal("0.30")
    assert record.lines[0]["debit"] == "0.10"

    audit = db.query(AuditLog).filter_by(action="journal_entry_created").one()
    assert audit.details["total_debit"] == "0.30"
    assert audit.details["total_credit"] == "0.30"


def test_journal_api_rejects_excess_scale_and_unbalanced_amounts(client, auth_headers):
    excess_scale = client.post(
        "/api/v1/journal/entries",
        headers=auth_headers,
        json={
            "date": "2026-07-15",
            "reference": "DECIMAL/INVALID-SCALE",
            "lines": [
                {"account": "1000", "debit": "1.001", "credit": "0"},
                {"account": "3000", "debit": "0", "credit": "1.001"},
            ],
        },
    )
    assert excess_scale.status_code == 422

    unbalanced = client.post(
        "/api/v1/journal/entries",
        headers=auth_headers,
        json={
            "date": "2026-07-15",
            "reference": "DECIMAL/UNBALANCED",
            "lines": [
                {"account": "1000", "debit": "100.00", "credit": "0.00"},
                {"account": "3000", "debit": "0.00", "credit": "99.99"},
            ],
        },
    )
    assert unbalanced.status_code == 422
    assert "not balanced" in unbalanced.json()["detail"]


def test_database_constraint_rejects_unbalanced_persisted_totals(db, seeded_user):
    db.add(
        JournalEntryRecord(
            organization_id=1,
            created_by_user_id=1,
            entry_date="2026-07-15",
            reference="DIRECT/UNBALANCED",
            memo="",
            status="draft",
            lines=[
                {"account": "1000", "debit": "10.00", "credit": "0.00"},
                {"account": "3000", "debit": "0.00", "credit": "9.99"},
            ],
            total_debit=Decimal("10.00"),
            total_credit=Decimal("9.99"),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_persisted_financial_columns_are_numeric_not_float():
    journal_table = JournalEntryRecord.__table__
    assert isinstance(journal_table.c.total_debit.type, Numeric)
    assert journal_table.c.total_debit.type.precision == 20
    assert journal_table.c.total_debit.type.scale == 2
    assert isinstance(journal_table.c.total_credit.type, Numeric)

    audit_table = BankReconciliationAuditLog.__table__
    for column_name in ("statement_total", "ledger_total", "difference"):
        column_type = audit_table.c[column_name].type
        assert isinstance(column_type, Numeric)
        assert column_type.precision == 20
        assert column_type.scale == 2


def test_static_journal_and_model_guards_prevent_float_regression():
    journal_source = Path("app/api/v1/journal.py").read_text(encoding="utf-8")
    core_source = Path("app/models/core.py").read_text(encoding="utf-8")
    bank_model_source = Path("app/models/bank_reconciliation.py").read_text(encoding="utf-8")

    assert "debit: float" not in journal_source
    assert "credit: float" not in journal_source
    assert "round(sum(" not in journal_source
    assert "mapped_column(Float" not in core_source
    assert "mapped_column(Float" not in bank_model_source
    assert "Numeric(20, 2)" in core_source
    assert "Numeric(20, 2)" in bank_model_source
