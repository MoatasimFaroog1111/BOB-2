"""Create and verify the isolated Odoo database used by Issue #117 UAT.

This helper is staging-only and contains no credentials. It uses Odoo's database
manager route, then verifies the new database through XML-RPC authentication.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


url = required("ODOO_UAT_URL").rstrip("/")
db = os.environ.get("ODOO_UAT_DB", "bob_uat_117").strip() or "bob_uat_117"
master_password = required("ODOO_UAT_MASTER_PASSWORD")
admin_login = os.environ.get("ODOO_UAT_ADMIN_LOGIN", "admin").strip() or "admin"
admin_password = required("ODOO_UAT_ADMIN_PASSWORD")

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
try:
    existing_uid = common.authenticate(db, admin_login, admin_password, {})
except Exception:
    existing_uid = False

created = False
if not existing_uid:
    form = urllib.parse.urlencode(
        {
            "master_pwd": master_password,
            "name": db,
            "login": admin_login,
            "password": admin_password,
            "phone": "",
            "lang": "en_US",
            "country_code": "SA",
            "demo": "false",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/web/database/create",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    try:
        with opener.open(request, timeout=180) as response:
            response.read(4096)
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"Odoo database manager returned HTTP {exc.code}: {body[:500]}") from exc
    created = True

uid = common.authenticate(db, admin_login, admin_password, {})
if not uid:
    raise RuntimeError("Database creation returned, but XML-RPC authentication failed")

print(
    "UAT117_DATABASE_RESULT="
    + json.dumps(
        {
            "database": db,
            "created": created,
            "verified": True,
            "admin_uid": int(uid),
            "data_class": "synthetic-non-production",
        },
        sort_keys=True,
    )
)
