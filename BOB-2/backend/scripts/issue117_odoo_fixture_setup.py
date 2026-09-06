"""Create/reuse the isolated SAR accounting fixture for Issue #117 live UAT."""
from __future__ import annotations

import json
import os
import sys
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
company_name = "BOB UAT 117 SAR"
bank_code = "101118"
charges_code = "601118"

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(db, login, password, {})
if not uid:
    raise RuntimeError("Unable to authenticate to isolated Odoo-UAT database")
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)


def call(model: str, method: str, args=None, kwargs=None):
    return models.execute_kw(db, uid, password, model, method, args or [], kwargs or {})


account_fields = call("account.account", "fields_get", [], {"attributes": ["type"]})
currency_ids = call("res.currency", "search", [[("name", "=", "SAR")]], {"limit": 1})
if not currency_ids:
    raise RuntimeError("SAR currency is not available in isolated Odoo-UAT")
sar_id = int(currency_ids[0])

company_ids = call("res.company", "search", [[("name", "=", company_name)]], {"limit": 1})
if company_ids:
    company_id = int(company_ids[0])
else:
    company_id = int(call("res.company", "create", [{"name": company_name, "currency_id": sar_id}]))
company = call("res.company", "read", [[company_id]], {"fields": ["currency_id"]})[0]
company_currency = company.get("currency_id")
company_currency_id = int(company_currency[0] if isinstance(company_currency, list) else company_currency)
if company_currency_id != sar_id:
    raise RuntimeError("UAT company is not SAR; refusing to continue")


def attach_account_to_company(account_id: int) -> None:
    if "company_ids" in account_fields:
        row = call("account.account", "read", [[account_id]], {"fields": ["company_ids"]})[0]
        existing = {int(x) for x in row.get("company_ids") or []}
        if company_id not in existing:
            call("account.account", "write", [[account_id], {"company_ids": [(4, company_id)]}])
    elif "company_id" in account_fields:
        row = call("account.account", "read", [[account_id]], {"fields": ["company_id"]})[0]
        current = row.get("company_id")
        current_id = int(current[0] if isinstance(current, list) else current) if current else None
        if current_id != company_id:
            call("account.account", "write", [[account_id], {"company_id": company_id}])


def find_or_create_account(code: str, name: str, account_type: str) -> int:
    global_ids = call("account.account", "search", [[("code", "=", code)]], {"limit": 1})
    if global_ids:
        account_id = int(global_ids[0])
        attach_account_to_company(account_id)
        call("account.account", "write", [[account_id], {"name": name, "account_type": account_type}])
        return account_id
    vals = {"code": code, "name": name, "account_type": account_type}
    if "company_ids" in account_fields:
        vals["company_ids"] = [(6, 0, [company_id])]
    elif "company_id" in account_fields:
        vals["company_id"] = company_id
    return int(call("account.account", "create", [vals]))


bank_account_id = find_or_create_account(bank_code, "UAT Bank", "asset_cash")
bank_charges_account_id = find_or_create_account(charges_code, "UAT Bank Charges", "expense")

journal_fields = call("account.journal", "fields_get", [], {"attributes": ["type"]})
journal_ids = call(
    "account.journal",
    "search",
    [[("name", "=", "UAT Bank Journal"), ("company_id", "=", company_id)]],
    {"limit": 1},
)
if journal_ids:
    journal_id = int(journal_ids[0])
else:
    vals = {"name": "UAT Bank Journal", "code": "U118", "type": "bank", "company_id": company_id}
    if "default_account_id" in journal_fields:
        vals["default_account_id"] = bank_account_id
    journal_id = int(call("account.journal", "create", [vals]))

result = {
    "database": db,
    "company_name": company_name,
    "company_id": company_id,
    "currency": "SAR",
    "journal_id": journal_id,
    "bank_account_code": bank_code,
    "bank_account_id": bank_account_id,
    "bank_charges_account_code": charges_code,
    "bank_charges_account_id": bank_charges_account_id,
    "odoo_uid": int(uid),
    "data_class": "synthetic-non-production",
}
print("UAT117_FIXTURE_RESULT=" + json.dumps(result, sort_keys=True))
sys.stdout.flush()
