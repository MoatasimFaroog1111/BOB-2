"""Initialize the isolated Odoo fixture used by Issue #117 live UAT.

This script is intentionally staging-only. It uses XML-RPC against the isolated
Odoo-UAT service and never contains credentials or customer data.
"""
from __future__ import annotations

import json
import os
import sys
import time
import xmlrpc.client


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


url = required("ODOO_UAT_URL").rstrip("/")
db = os.environ.get("ODOO_UAT_DB", "bob_uat_117").strip() or "bob_uat_117"
login = os.environ.get("ODOO_UAT_ADMIN_LOGIN", "admin").strip() or "admin"
password = required("ODOO_UAT_ADMIN_PASSWORD")

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(db, login, password, {})
if not uid:
    raise RuntimeError("Unable to authenticate to isolated Odoo-UAT database")
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)


def call(model: str, method: str, args=None, kwargs=None):
    return models.execute_kw(db, uid, password, model, method, args or [], kwargs or {})


def fields(model: str) -> dict:
    return call(model, "fields_get", [], {"attributes": ["type", "required", "relation"]})


# Install Accounting through Odoo's own module registry. This is more reliable
# for the container image than relying on an entrypoint CLI install attempt.
modules = call(
    "ir.module.module",
    "search_read",
    [[("name", "=", "account")]],
    {"fields": ["id", "name", "state"], "limit": 1},
)
if not modules:
    raise RuntimeError("Odoo-UAT image does not expose the account module")
if modules[0].get("state") != "installed":
    call("ir.module.module", "button_immediate_install", [[int(modules[0]["id"])]] )
    # Re-authenticate after registry reload and prove the model exists.
    for _ in range(30):
        time.sleep(1)
        try:
            uid = common.authenticate(db, login, password, {})
            if uid:
                models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
                fields("account.account")
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Accounting module installation did not expose account.account")

company_ids = call("res.company", "search", [[]], {"limit": 1})
if not company_ids:
    raise RuntimeError("Odoo-UAT has no company after account module initialization")
company_id = int(company_ids[0])

currency_ids = call("res.currency", "search", [[("name", "=", "SAR")]], {"limit": 1})
company_vals = {"name": "BOB UAT 117"}
if currency_ids:
    company_vals["currency_id"] = int(currency_ids[0])
call("res.company", "write", [[company_id], company_vals])

account_fields = fields("account.account")


def find_or_create_account(code: str, name: str, account_type: str) -> int:
    domain = [("code", "=", code)]
    if "company_id" in account_fields:
        domain.append(("company_id", "=", company_id))
    ids = call("account.account", "search", [domain], {"limit": 1})
    if ids:
        return int(ids[0])
    vals = {"code": code, "name": name, "account_type": account_type}
    if "company_id" in account_fields:
        vals["company_id"] = company_id
    elif "company_ids" in account_fields:
        vals["company_ids"] = [(6, 0, [company_id])]
    return int(call("account.account", "create", [vals]))


bank_account_id = find_or_create_account("101117", "UAT Bank", "asset_cash")
bank_charges_account_id = find_or_create_account("601117", "UAT Bank Charges", "expense")

journal_fields = fields("account.journal")
journal_domain = [("type", "=", "bank")]
if "company_id" in journal_fields:
    journal_domain.append(("company_id", "=", company_id))
journal_ids = call("account.journal", "search", [journal_domain], {"limit": 1})
if journal_ids:
    journal_id = int(journal_ids[0])
    vals = {"name": "UAT Bank Journal"}
    if "default_account_id" in journal_fields:
        vals["default_account_id"] = bank_account_id
    call("account.journal", "write", [[journal_id], vals])
else:
    vals = {"name": "UAT Bank Journal", "code": "UATB", "type": "bank"}
    if "company_id" in journal_fields:
        vals["company_id"] = company_id
    if "default_account_id" in journal_fields:
        vals["default_account_id"] = bank_account_id
    journal_id = int(call("account.journal", "create", [vals]))

result = {
    "database": db,
    "company_id": company_id,
    "journal_id": journal_id,
    "bank_account_id": bank_account_id,
    "bank_charges_account_id": bank_charges_account_id,
    "odoo_uid": int(uid),
    "data_class": "synthetic-non-production",
}
print("UAT117_FIXTURE_RESULT=" + json.dumps(result, sort_keys=True))
sys.stdout.flush()
