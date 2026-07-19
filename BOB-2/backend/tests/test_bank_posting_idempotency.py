"""Regression evidence for safe Odoo bank-posting retries."""

from decimal import Decimal
from pathlib import Path

from app.api.v1.bank_posting_v2 import (
    BankPostingLineV2,
    BankPostingRequestV2,
    build_idempotency_key,
)


def _payload(**overrides) -> BankPostingRequestV2:
    values = {
        "company_id": 7,
        "date": "2026-07-15",
        "ref": "BANK/STMT/2026-07",
        "statement_ref": "SA-BANK-ROW-42",
        "row_number": 42,
        "amount": Decimal("7084.63"),
        "lines": [
            BankPostingLineV2(
                account_id=1010,
                debit=Decimal("7084.63"),
                credit=Decimal("0.00"),
                name="Bank receipt",
            ),
            BankPostingLineV2(
                account_id=4000,
                debit=Decimal("0.00"),
                credit=Decimal("7084.63"),
                name="Bank receipt",
            ),
        ],
    }
    values.update(overrides)
    return BankPostingRequestV2(**values)


def test_same_source_row_builds_same_key_on_every_retry():
    first = build_idempotency_key(organization_id=3, company_id=7, payload=_payload())
    retry = build_idempotency_key(organization_id=3, company_id=7, payload=_payload())

    assert first == retry
    assert len(first) == 64


def test_explicit_upstream_key_is_preserved_for_retry_contract():
    payload = _payload(idempotency_key=" pilot-import-2026-07-row-42 ")

    assert (
        build_idempotency_key(organization_id=3, company_id=7, payload=payload)
        == "pilot-import-2026-07-row-42"
    )


def test_key_is_scoped_by_tenant_and_odoo_company():
    payload = _payload()

    tenant_a = build_idempotency_key(organization_id=3, company_id=7, payload=payload)
    tenant_b = build_idempotency_key(organization_id=4, company_id=7, payload=payload)
    other_company = build_idempotency_key(organization_id=3, company_id=8, payload=payload)

    assert len({tenant_a, tenant_b, other_company}) == 3


def test_material_source_change_produces_a_new_key():
    original = build_idempotency_key(3, 7, _payload())
    changed_amount = build_idempotency_key(
        3,
        7,
        _payload(
            amount=Decimal("7084.64"),
            lines=[
                BankPostingLineV2(
                    account_id=1010,
                    debit=Decimal("7084.64"),
                    credit=Decimal("0.00"),
                    name="Bank receipt",
                ),
                BankPostingLineV2(
                    account_id=4000,
                    debit=Decimal("0.00"),
                    credit=Decimal("7084.64"),
                    name="Bank receipt",
                ),
            ],
        ),
    )
    changed_row = build_idempotency_key(3, 7, _payload(row_number=43))

    assert original != changed_amount
    assert original != changed_row


def test_duplicate_lookup_remains_before_odoo_move_creation():
    """Guard the ordering that makes a retry read-only in Odoo."""

    source = Path("app/api/v1/bank_posting_v2.py").read_text(encoding="utf-8")
    lookup = source.index('"account.move",\n            "search_read"')
    duplicate_return = source.index('"status": "duplicate_prevented"')
    create = source.index('"account.move", "create"')

    assert lookup < duplicate_return < create
