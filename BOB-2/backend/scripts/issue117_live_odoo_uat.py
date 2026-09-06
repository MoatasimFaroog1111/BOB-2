"""Execute Issue #117 live UAT against the isolated Odoo-UAT database only.

The runner uses BOB-2's real bank-posting boundary for First Write and Retry,
then independently reads Odoo and BOB's immutable audit log. It fails closed on
any duplicate, imbalance, wrong fixture scope, or missing audit evidence.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal

from starlette.requests import Request

from app.api.v1.bank_posting_v2 import (
    BankPostingLineV2,
    BankPostingRequestV2,
    register_bank_reconciliation_entry_v2,
)
from app.db.database import SessionLocal
from app.predeploy import main as predeploy_main
from app.models.core import AuditLog, ERPConnection, User
from app.security.encryption import encrypt_value
from app.security.tenant_scope import tenant_scope
from app.erp.factory import get_erp_provider


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def only_isolated_odoo(url: str, database: str) -> None:
    lowered = url.lower()
    if database != "bob_uat_117":
        raise RuntimeError("Refusing UAT against any database except bob_uat_117")
    if "odoo-uat" not in lowered:
        raise RuntimeError("Refusing UAT against an Odoo host outside isolated Odoo-UAT")


def simple_request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/register-bank-reconciliation-entry-v2",
            "raw_path": b"/api/v1/register-bank-reconciliation-entry-v2",
            "query_string": b"",
            "headers": [(b"user-agent", b"issue117-live-uat")],
            "client": ("127.0.0.1", 11700),
            "server": ("uat-runner", 80),
        }
    )


odoo_url = required("ODOO_UAT_URL").rstrip("/")
odoo_db = os.environ.get("ODOO_UAT_DB", "bob_uat_117").strip() or "bob_uat_117"
odoo_login = required("ODOO_UAT_ADMIN_LOGIN")
odoo_password = required("ODOO_UAT_ADMIN_PASSWORD")
seed_email = required("GUARDIAN_SEED_EMAIL").lower()
company_name = "BOB UAT 117 SAR"
only_isolated_odoo(odoo_url, odoo_db)

predeploy_main()

erp = get_erp_provider(
    provider="odoo",
    url=odoo_url,
    db=odoo_db,
    username=odoo_login,
    password=odoo_password,
)

companies = erp.execute_kw(
    "res.company", "search_read", [[['name', '=', company_name]]],
    {"fields": ["id", "name", "currency_id"], "limit": 1},
)
if not companies:
    raise RuntimeError(f"Isolated Odoo fixture company {company_name} was not found")
company_id = int(companies[0]["id"])
currency_value = companies[0].get("currency_id")
currency_name = currency_value[1] if isinstance(currency_value, list) and len(currency_value) > 1 else ""
if currency_name != "SAR":
    raise RuntimeError(f"UAT company currency is {currency_name!r}, expected SAR")

journals = erp.execute_kw(
    "account.journal", "search_read",
    [[['name', '=', 'UAT Bank Journal'], ['company_id', '=', company_id]]],
    {"fields": ["id", "name", "type", "company_id"], "limit": 1},
)
if not journals:
    raise RuntimeError("UAT Bank Journal was not found")
journal_id = int(journals[0]["id"])

account_fields = erp.execute_kw(
    "account.account", "fields_get", [], {"attributes": ["type"]}
)
account_domain = [['code', 'in', ['101117', '601117']]]
if "company_id" in account_fields:
    account_domain.append(['company_id', '=', company_id])
elif "company_ids" in account_fields:
    account_domain.append(['company_ids', 'in', [company_id]])
accounts = erp.execute_kw(
    "account.account", "search_read",
    [account_domain],
    {"fields": ["id", "code", "name"], "limit": 10},
)
by_code = {str(row.get("code")): row for row in accounts}
if set(by_code) != {"101117", "601117"}:
    raise RuntimeError(f"UAT account fixture is incomplete: {sorted(by_code)}")
bank_account_id = int(by_code["101117"]["id"])
bank_charges_account_id = int(by_code["601117"]["id"])

session = SessionLocal()
try:
    user = session.query(User).filter(User.email == seed_email).first()
    if not user or user.organization_id is None:
        raise RuntimeError("BOB UAT owner was not seeded")
    organization_id = int(user.organization_id)

    with tenant_scope(organization_id):
        secret_ref = encrypt_value(
            json.dumps({"username": odoo_login, "password": odoo_password})
        )
        connection = (
            session.query(ERPConnection)
            .filter(ERPConnection.organization_id == organization_id)
            .first()
        )
        if connection is None:
            connection = ERPConnection(
                organization_id=organization_id,
                provider="odoo",
                base_url=odoo_url,
                database_name=odoo_db,
                auth_type="password",
                encrypted_secret_ref=secret_ref,
                is_active=True,
            )
            session.add(connection)
        else:
            connection.provider = "odoo"
            connection.base_url = odoo_url
            connection.database_name = odoo_db
            connection.auth_type = "password"
            connection.encrypted_secret_ref = secret_ref
            connection.is_active = True
        session.commit()

        payload = BankPostingRequestV2(
            company_id=company_id,
            journal_type="bank",
            journal_id=journal_id,
            date="2026-08-06",
            ref="UAT117/BANK-FEE/2026-08",
            filename="issue117_synthetic_bank_statement.csv",
            amount=Decimal("57.50"),
            statement_ref="UAT117-STMT-006",
            row_number=6,
            approval_status="approved",
            lines=[
                BankPostingLineV2(
                    account_id=bank_charges_account_id,
                    account_code="601117",
                    account_name="UAT Bank Charges",
                    debit=Decimal("57.50"),
                    credit=Decimal("0.00"),
                    name="Synthetic UAT bank service fee",
                ),
                BankPostingLineV2(
                    account_id=bank_account_id,
                    account_code="101117",
                    account_name="UAT Bank",
                    debit=Decimal("0.00"),
                    credit=Decimal("57.50"),
                    name="Synthetic UAT bank service fee",
                ),
            ],
        )

        token = {"sub": user.email}
        first = register_bank_reconciliation_entry_v2(
            payload, simple_request(), db_session=session, token_payload=token
        )
        retry = register_bank_reconciliation_entry_v2(
            payload, simple_request(), db_session=session, token_payload=token
        )

        if first.get("status") != "success":
            raise RuntimeError(f"First Write did not succeed: {first.get('status')}")
        if retry.get("status") != "duplicate_prevented":
            raise RuntimeError(f"Retry did not prevent duplicate: {retry.get('status')}")
        move_id = int(first["move_id"])
        if int(retry["move_id"]) != move_id:
            raise RuntimeError("Retry returned a different Odoo move")
        if retry.get("idempotency_key") != first.get("idempotency_key"):
            raise RuntimeError("Retry idempotency identity changed")

        full_ref = f"{payload.ref} | BOB-IDEMP:{first['idempotency_key']}"
        moves = erp.execute_kw(
            "account.move", "search_read",
            [[['ref', '=', full_ref], ['company_id', '=', company_id]]],
            {"fields": ["id", "name", "state", "date", "journal_id", "ref"], "limit": 10},
        )
        if len(moves) != 1 or int(moves[0]["id"]) != move_id:
            raise RuntimeError(f"Expected exactly one Odoo move; found {len(moves)}")

        lines = erp.execute_kw(
            "account.move.line", "search_read",
            [[['move_id', '=', move_id]]],
            {"fields": ["id", "account_id", "debit", "credit", "name"], "limit": 20},
        )
        total_debit = sum(Decimal(str(row.get("debit") or 0)) for row in lines)
        total_credit = sum(Decimal(str(row.get("credit") or 0)) for row in lines)
        line_account_ids = {
            int(row["account_id"][0] if isinstance(row.get("account_id"), list) else row["account_id"])
            for row in lines if row.get("account_id")
        }
        if total_debit != Decimal("57.50") or total_credit != Decimal("57.50"):
            raise RuntimeError(f"Unexpected move totals: debit={total_debit} credit={total_credit}")
        if not {bank_account_id, bank_charges_account_id}.issubset(line_account_ids):
            raise RuntimeError("Odoo move does not contain both approved UAT accounts")

        audits = (
            session.query(AuditLog)
            .filter(
                AuditLog.organization_id == organization_id,
                AuditLog.entity_type == "bank_reconciliation_posting",
                AuditLog.entity_id == str(move_id),
                AuditLog.action.in_([
                    "odoo_bank_reconciliation_entry_created",
                    "odoo_duplicate_prevented",
                ]),
            )
            .order_by(AuditLog.sequence_number.asc())
            .all()
        )
        actions = [row.action for row in audits]
        if "odoo_bank_reconciliation_entry_created" not in actions:
            raise RuntimeError("Missing First Write audit event")
        if "odoo_duplicate_prevented" not in actions:
            raise RuntimeError("Missing Retry duplicate-prevented audit event")
        create_index = actions.index("odoo_bank_reconciliation_entry_created")
        retry_index = actions.index("odoo_duplicate_prevented")
        if create_index >= retry_index:
            raise RuntimeError("Audit event ordering is invalid")

        result = {
            "status": "PASS",
            "data_class": "synthetic-non-production",
            "railway_environment": os.environ.get("RAILWAY_ENVIRONMENT_NAME", ""),
            "tested_commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", ""),
            "odoo_database": odoo_db,
            "company_name": company_name,
            "company_id": company_id,
            "currency": "SAR",
            "journal_id": journal_id,
            "bank_account_id": bank_account_id,
            "bank_charges_account_id": bank_charges_account_id,
            "first_write_status": first.get("status"),
            "retry_status": retry.get("status"),
            "move_id": move_id,
            "move_count": len(moves),
            "move_state": moves[0].get("state"),
            "idempotency_key": first.get("idempotency_key"),
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "audit": [
                {
                    "sequence": int(row.sequence_number),
                    "action": row.action,
                    "event_hash": row.event_hash,
                    "previous_hash": row.previous_hash,
                }
                for row in audits
            ],
        }
        print("UAT117_LIVE_RESULT=" + json.dumps(result, sort_keys=True))
finally:
    session.close()
