"""Read-only Odoo reference catalog for the BOB Bank Rules settings page.

This service deliberately resolves one tenant ERP provider and reuses it for all
reference queries. With OdooProvider UID caching, the full catalog requires one
/xmlrpc/2/common authentication instead of several concurrent authentications.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.tenant_erp_service import TenantERPResolver, tenant_erp_resolver


class BankRuleReferenceCatalogService:
    def __init__(self, resolver: TenantERPResolver = tenant_erp_resolver) -> None:
        self._resolver = resolver

    @staticmethod
    def _m2o_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            return int(value[0]) if value[0] else None
        if value:
            return int(value)
        return None

    @staticmethod
    def _default_company_id(erp: Any) -> int | None:
        username = str(getattr(erp, "username", "") or "")
        if not username:
            return None
        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1},
        )
        if not users:
            return None
        return BankRuleReferenceCatalogService._m2o_id(users[0].get("company_id"))

    @staticmethod
    def _journals(erp: Any, company_id: int | None) -> list[dict[str, Any]]:
        domain: list = [["active", "=", True], ["type", "=", "bank"]]
        if company_id:
            domain.append(["company_id", "=", company_id])
        return erp.execute_kw(
            "account.journal",
            "search_read",
            [domain],
            {
                "fields": ["id", "code", "name", "type", "company_id"],
                "order": "code asc, id asc",
                "limit": 200,
            },
        )

    @staticmethod
    def _accounts(erp: Any, company_id: int | None) -> list[dict[str, Any]]:
        domain: list = []
        if company_id:
            domain.append(["company_ids", "in", [company_id]])
        return erp.execute_kw(
            "account.account",
            "search_read",
            [domain],
            {
                "fields": ["id", "code", "name"],
                "order": "code asc",
                "limit": 2000,
            },
        )

    @staticmethod
    def _partners(erp: Any, company_id: int | None) -> list[dict[str, Any]]:
        domain: list = [
            ("active", "=", True),
            "|",
            ("customer_rank", ">", 0),
            ("supplier_rank", ">", 0),
        ]
        if company_id:
            domain.extend(["|", ("company_id", "=", False), ("company_id", "=", company_id)])
        fields = ["id", "name", "customer_rank", "supplier_rank", "company_id"]
        try:
            rows = erp.execute_kw(
                "res.partner",
                "search_read",
                [domain],
                {"fields": fields, "order": "name asc", "limit": 5000},
            )
        except Exception:
            fallback_domain: list = [("active", "=", True)]
            if company_id:
                fallback_domain.extend(
                    ["|", ("company_id", "=", False), ("company_id", "=", company_id)]
                )
            rows = erp.execute_kw(
                "res.partner",
                "search_read",
                [fallback_domain],
                {"fields": ["id", "name", "company_id"], "order": "name asc", "limit": 5000},
            )
        return [
            {
                "id": row.get("id"),
                "name": row.get("name") or "",
                "customer_rank": int(row.get("customer_rank") or 0),
                "supplier_rank": int(row.get("supplier_rank") or 0),
                "company_id": row.get("company_id"),
            }
            for row in rows
            if str(row.get("name") or "").strip()
        ]

    @staticmethod
    def _analytic_accounts(erp: Any, company_id: int | None) -> list[dict[str, Any]]:
        domain: list = [["active", "=", True]]
        if company_id:
            domain.extend(["|", ["company_id", "=", False], ["company_id", "=", company_id]])
        return erp.execute_kw(
            "account.analytic.account",
            "search_read",
            [domain],
            {"fields": ["id", "name"], "order": "name asc", "limit": 1000},
        )

    def load(
        self,
        db: Session,
        *,
        organization_id: int,
        company_id: int | None = None,
    ) -> dict[str, Any]:
        try:
            _connection, erp = self._resolver.resolve(db, organization_id)
            if str(getattr(erp, "provider_name", "")).lower() != "odoo":
                raise HTTPException(
                    status_code=422,
                    detail="BOB Bank Rules reference catalog currently requires an Odoo ERP connection.",
                )
            effective_company_id = company_id or self._default_company_id(erp)
            return {
                "status": "success",
                "company_id": effective_company_id,
                "journals": self._journals(erp, effective_company_id),
                "accounts": self._accounts(erp, effective_company_id),
                "partners": self._partners(erp, effective_company_id),
                "analytic_accounts": self._analytic_accounts(erp, effective_company_id),
            }
        except HTTPException:
            raise
        except xmlrpc.client.ProtocolError as exc:
            if int(getattr(exc, "errcode", 0) or 0) == 429:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Odoo temporarily rate-limited XML-RPC authentication (429). "
                        "BOB now consolidates Bank Rules reference loading into one session; retry shortly."
                    ),
                ) from exc
            raise HTTPException(
                status_code=502,
                detail=f"Odoo reference catalog request failed with HTTP {getattr(exc, 'errcode', 'error')}.",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to load Odoo Bank Rules references: {type(exc).__name__}",
            ) from exc


bank_rule_reference_catalog_service = BankRuleReferenceCatalogService()
