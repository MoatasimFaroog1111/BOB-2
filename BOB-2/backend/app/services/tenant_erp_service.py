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

    @staticmethod
    def _m2o_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            try:
                return int(value[0]) if value[0] else None
            except (TypeError, ValueError):
                return None
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def account(self, erp: Any, account_id: int) -> dict[str, Any]:
        row = self._read_one(erp, "account.account", account_id, ["id", "code", "name"])
        if not str(row.get("code") or "").strip() or not str(row.get("name") or "").strip():
            raise HTTPException(status_code=422, detail="Referenced Odoo account is missing code/name metadata.")
        return row

    def partner(self, erp: Any, partner_id: int) -> dict[str, Any]:
        return self._read_one(erp, "res.partner", partner_id, ["id", "name"])

    def analytic_account(self, erp: Any, analytic_account_id: int) -> dict[str, Any]:
        return self._read_one(erp, "account.analytic.account", analytic_account_id, ["id", "name"])

    def _simple_repartition_account_id(
        self,
        erp: Any,
        repartition_ids: list[int],
        *,
        label: str,
    ) -> int:
        if not repartition_ids:
            raise HTTPException(status_code=422, detail=f"Referenced Odoo tax has no {label} repartition lines.")
        rows = erp.execute_kw(
            "account.tax.repartition.line",
            "search_read",
            [[["id", "in", repartition_ids]]],
            {"fields": ["id", "repartition_type", "factor_percent", "account_id"], "limit": len(repartition_ids)},
        )
        tax_rows: list[tuple[int, float]] = []
        for row in rows or []:
            if str(row.get("repartition_type") or "") != "tax":
                continue
            account_id = self._m2o_id(row.get("account_id"))
            try:
                factor = float(row.get("factor_percent") or 0)
            except (TypeError, ValueError):
                factor = 0.0
            if account_id and factor > 0:
                tax_rows.append((account_id, factor))
        account_ids = {account_id for account_id, _factor in tax_rows}
        total_factor = sum(factor for _account_id, factor in tax_rows)
        if len(account_ids) != 1 or abs(total_factor - 100.0) > 0.01:
            raise HTTPException(
                status_code=422,
                detail=f"Referenced Odoo tax uses a complex {label} repartition; Bank Rules require one 100% tax posting account.",
            )
        return next(iter(account_ids))

    def tax(self, erp: Any, tax_id: int, company_id: int | None = None) -> dict[str, Any]:
        """Resolve one simple percentage tax and a direction-safe Odoo posting account.

        Bank Rules fail closed for grouped/fixed/custom taxes, cross-company references,
        complex repartitions, and taxes whose invoice/refund tax accounts differ. This
        avoids silently using an invoice VAT account for refunds when Odoo is configured
        with a different refund account.
        """
        tax = self._read_one(
            erp,
            "account.tax",
            tax_id,
            [
                "id", "name", "active", "amount", "amount_type", "type_tax_use",
                "price_include", "company_id", "invoice_repartition_line_ids",
                "refund_repartition_line_ids",
            ],
        )
        if not bool(tax.get("active", True)):
            raise HTTPException(status_code=422, detail="Referenced Odoo tax is inactive.")
        tax_company_id = self._m2o_id(tax.get("company_id"))
        if company_id and tax_company_id and int(company_id) != tax_company_id:
            raise HTTPException(status_code=422, detail="Referenced Odoo tax belongs to another company.")
        if str(tax.get("amount_type") or "") != "percent":
            raise HTTPException(
                status_code=422,
                detail="BOB Bank Rules currently support simple Odoo percentage taxes only.",
            )
        try:
            rate = float(tax.get("amount") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Referenced Odoo tax has an invalid percentage.") from exc
        if rate <= 0 or rate >= 100:
            raise HTTPException(status_code=422, detail="Referenced Odoo tax percentage must be greater than 0 and less than 100.")

        invoice_ids = [
            int(value)
            for value in (tax.get("invoice_repartition_line_ids") or [])
            if isinstance(value, int) and value > 0
        ]
        refund_ids = [
            int(value)
            for value in (tax.get("refund_repartition_line_ids") or [])
            if isinstance(value, int) and value > 0
        ]
        invoice_account_id = self._simple_repartition_account_id(erp, invoice_ids, label="invoice")
        refund_account_id = self._simple_repartition_account_id(erp, refund_ids, label="refund")
        if invoice_account_id != refund_account_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Referenced Odoo tax uses different invoice and refund posting accounts. "
                    "BOB Bank Rules reject this tax until direction-specific refund posting is configured explicitly."
                ),
            )

        tax_account = self.account(erp, invoice_account_id)
        return {
            "id": int(tax["id"]),
            "name": str(tax.get("name") or ""),
            "amount": rate,
            "amount_type": "percent",
            "type_tax_use": str(tax.get("type_tax_use") or ""),
            "price_include": bool(tax.get("price_include")),
            "company_id": tax_company_id,
            "tax_account_id": int(tax_account["id"]),
            "tax_account_code": str(tax_account.get("code") or ""),
            "tax_account_name": str(tax_account.get("name") or ""),
        }

    def target_snapshot(
        self,
        erp: Any,
        target: dict[str, Any],
        company_id: int | None = None,
    ) -> dict[str, Any]:
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
            "tax_id": None,
            "tax_name": "",
            "tax_rate": None,
            "tax_amount_type": "",
            "tax_type_use": "",
            "tax_price_include": False,
            "tax_account_id": None,
            "tax_account_code": "",
            "tax_account_name": "",
            "tax_amount_mode": None,
            "tax_company_id": None,
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
        tax_id = int(target.get("tax_id") or 0)
        if tax_id > 0:
            stored_tax_company_id = self._m2o_id(target.get("tax_company_id"))
            if company_id and stored_tax_company_id and int(company_id) != stored_tax_company_id:
                raise HTTPException(status_code=422, detail="Stored Bank Rule tax company does not match the selected company.")
            effective_tax_company_id = int(company_id or stored_tax_company_id or 0) or None
            if not effective_tax_company_id:
                raise HTTPException(
                    status_code=422,
                    detail="Bank Rule tax company is unresolved; reconfigure the tax from the rule's bank journal company.",
                )
            tax = self.tax(erp, tax_id, company_id=effective_tax_company_id)
            snapshot.update({
                "tax_id": int(tax["id"]),
                "tax_name": str(tax.get("name") or ""),
                "tax_rate": tax.get("amount"),
                "tax_amount_type": str(tax.get("amount_type") or ""),
                "tax_type_use": str(tax.get("type_tax_use") or ""),
                "tax_price_include": bool(tax.get("price_include")),
                "tax_account_id": int(tax["tax_account_id"]),
                "tax_account_code": str(tax.get("tax_account_code") or ""),
                "tax_account_name": str(tax.get("tax_account_name") or ""),
                "tax_amount_mode": "included_in_bank_amount",
                "tax_company_id": effective_tax_company_id,
            })
        return snapshot


tenant_erp_resolver = TenantERPResolver()
odoo_reference_validator = OdooReferenceValidator()
