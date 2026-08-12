"""Shared tenant ERP access and accounting-reference validation.

This boundary owns credential resolution and read-only verification of Odoo references.
Business components consume validated IDs/snapshots and never handle decrypted secrets.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value


class TenantERPResolver:
    def resolve(self, db: Session, organization_id: int):
        connection = (
            db.query(ERPConnection)
            .filter(
                ERPConnection.organization_id == organization_id,
                ERPConnection.is_active.is_(True),
            )
            .order_by(ERPConnection.id.asc())
            .first()
        )
        if not connection or not connection.encrypted_secret_ref:
            raise HTTPException(status_code=404, detail="No active ERP connection found.")
        try:
            secret = json.loads(decrypt_value(connection.encrypted_secret_ref))
            username = str(secret["username"])
            password = str(secret["password"])
        except Exception as exc:
            raise HTTPException(status_code=503, detail="ERP credentials are unavailable.") from exc

        provider = get_erp_provider(
            provider=connection.provider,
            url=connection.base_url,
            db=connection.database_name or "",
            username=username,
            password=password,
        )
        return connection, provider


class OdooReferenceValidator:
    """Validate BOB Bank Rule references against the currently connected Odoo."""

    @staticmethod
    def bank_journal(erp: Any, journal_id: int, company_id: int | None = None) -> dict[str, Any]:
        journals = erp.discover_bank_journals(company_id=company_id)
        selected = next(
            (row for row in journals if int(row.get("journal_id") or 0) == int(journal_id)),
            None,
        )
        if not selected:
            raise HTTPException(status_code=422, detail="Referenced journal is not an active Odoo bank journal.")
        if int(selected.get("account_id") or 0) <= 0:
            raise HTTPException(status_code=422, detail="Referenced Odoo bank journal has no liquidity account.")
        return selected

    @staticmethod
    def _read_one(erp: Any, model: str, record_id: int, fields: list[str]) -> dict[str, Any]:
        rows = erp.execute_kw(
            model,
            "search_read",
            [[["id", "=", int(record_id)]]],
            {"fields": fields, "limit": 1},
        )
        if not rows:
            raise HTTPException(status_code=422, detail=f"Referenced {model} record {record_id} does not exist in Odoo.")
        return dict(rows[0])

    def account(self, erp: Any, account_id: int) -> dict[str, Any]:
        row = self._read_one(erp, "account.account", account_id, ["id", "code", "name"])
        if not str(row.get("code") or "").strip() or not str(row.get("name") or "").strip():
            raise HTTPException(status_code=422, detail="Referenced Odoo account is missing code/name metadata.")
        return row

    def partner(self, erp: Any, partner_id: int) -> dict[str, Any]:
        return self._read_one(erp, "res.partner", partner_id, ["id", "name"])

    def analytic_account(self, erp: Any, analytic_account_id: int) -> dict[str, Any]:
        return self._read_one(erp, "account.analytic.account", analytic_account_id, ["id", "name"])

    def target_snapshot(self, erp: Any, target: dict[str, Any]) -> dict[str, Any]:
        account_id = int(target.get("account_id") or 0)
        if account_id <= 0:
            raise HTTPException(status_code=422, detail="A valid Odoo counterpart account is required.")
        account = self.account(erp, account_id)
        snapshot: dict[str, Any] = {
            "account_id": int(account["id"]),
            "account_code": str(account.get("code") or ""),
            "account_name": str(account.get("name") or ""),
            "partner_id": None,
            "partner_name": "",
            "analytic_account_id": None,
            "analytic_account_name": "",
        }
        partner_id = int(target.get("partner_id") or 0)
        if partner_id > 0:
            partner = self.partner(erp, partner_id)
            snapshot["partner_id"] = int(partner["id"])
            snapshot["partner_name"] = str(partner.get("name") or "")
        analytic_id = int(target.get("analytic_account_id") or 0)
        if analytic_id > 0:
            analytic = self.analytic_account(erp, analytic_id)
            snapshot["analytic_account_id"] = int(analytic["id"])
            snapshot["analytic_account_name"] = str(analytic.get("name") or "")
        return snapshot


tenant_erp_resolver = TenantERPResolver()
odoo_reference_validator = OdooReferenceValidator()
