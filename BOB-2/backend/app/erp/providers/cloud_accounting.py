"""Connection adapters for major cloud accounting/ERP systems.

These adapters implement the small ERPConnectionProvider contract only.  Odoo's
richer discovery/command capabilities remain isolated in OdooProvider.  OAuth
providers accept an already-issued access token; token issuance/refresh is a
separate authorization concern and is deliberately not mixed into this layer.
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from app.erp.rest_transport import request_json


def _basic_auth(username: str, password: str) -> str:
    if not username or not password:
        raise ValueError("Username and password are required for this ERP provider.")
    encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _bearer_auth(token: str) -> str:
    value = token.strip()
    if not value:
        raise ValueError("An OAuth access token is required for this ERP provider.")
    return f"Bearer {value}"


class SAPS4HANAProvider:
    provider_name = "sap_s4hana"

    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url
        self.db = db
        self.username = username
        self.password = password

    def _probe(self) -> dict[str, Any]:
        return request_json(
            base_url=self.url,
            method="GET",
            path="/sap/opu/odata/SAP/API_BUSINESS_PARTNER/A_BusinessPartner?$top=1&$format=json",
            headers={"Authorization": _basic_auth(self.username, self.password)},
        )

    def test_connection(self) -> dict[str, Any]:
        payload = self._probe()
        return {
            "provider": self.provider_name,
            "connected": True,
            "system": "SAP S/4HANA",
            "database_or_tenant": self.db or None,
            "probe": "Business Partner OData API",
            "result_available": bool(payload),
        }

    def get_company_info(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "system": "SAP S/4HANA",
            "database_or_tenant": self.db or None,
            "connection_verified": bool(self._probe() is not None),
        }


class OracleFusionERPProvider:
    provider_name = "oracle_fusion"

    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url
        self.db = db
        self.username = username
        self.password = password

    def _ledgers(self) -> dict[str, Any]:
        return request_json(
            base_url=self.url,
            method="GET",
            path="/fscmRestApi/resources/11.13.18.05/ledgersLOV?limit=1",
            headers={
                "Authorization": _basic_auth(self.username, self.password),
                "Content-Type": "application/vnd.oracle.adf.resourcecollection+json",
            },
        )

    def test_connection(self) -> dict[str, Any]:
        payload = self._ledgers()
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return {
            "provider": self.provider_name,
            "connected": True,
            "system": "Oracle Fusion Cloud ERP",
            "tenant": self.db or None,
            "ledger_visible": bool(items),
        }

    def get_company_info(self) -> dict[str, Any]:
        payload = self._ledgers()
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        return {
            "provider": self.provider_name,
            "system": "Oracle Fusion Cloud ERP",
            "tenant": self.db or None,
            "ledger": {
                "id": first.get("LedgerId"),
                "name": first.get("Name"),
                "category": first.get("LedgerCategoryCode"),
            }
            if first
            else None,
        }


class BusinessCentralProvider:
    provider_name = "business_central"

    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url
        self.db = db
        self.username = username
        self.password = password

    def _companies(self) -> dict[str, Any]:
        return request_json(
            base_url=self.url,
            method="GET",
            path="/api/v2.0/companies",
            headers={"Authorization": _bearer_auth(self.password)},
        )

    def test_connection(self) -> dict[str, Any]:
        payload = self._companies()
        companies = payload.get("value") if isinstance(payload.get("value"), list) else []
        return {
            "provider": self.provider_name,
            "connected": True,
            "system": "Microsoft Dynamics 365 Business Central",
            "environment": self.db or None,
            "companies_count": len(companies),
        }

    def get_company_info(self) -> dict[str, Any]:
        payload = self._companies()
        companies = payload.get("value") if isinstance(payload.get("value"), list) else []
        safe_companies = []
        for row in companies[:20]:
            if isinstance(row, dict):
                safe_companies.append(
                    {
                        "id": row.get("id"),
                        "name": row.get("name"),
                        "displayName": row.get("displayName"),
                    }
                )
        return {
            "provider": self.provider_name,
            "system": "Microsoft Dynamics 365 Business Central",
            "companies": safe_companies,
        }


class QuickBooksOnlineProvider:
    provider_name = "quickbooks_online"

    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url
        self.db = db.strip()
        self.username = username
        self.password = password
        if not self.db:
            raise ValueError("QuickBooks realm/company ID is required.")

    def _company(self) -> dict[str, Any]:
        realm = quote(self.db, safe="")
        return request_json(
            base_url=self.url,
            method="GET",
            path=f"/v3/company/{realm}/companyinfo/{realm}",
            headers={"Authorization": _bearer_auth(self.password)},
        )

    def test_connection(self) -> dict[str, Any]:
        payload = self._company()
        company = payload.get("CompanyInfo")
        return {
            "provider": self.provider_name,
            "connected": True,
            "system": "QuickBooks Online",
            "realm_id": self.db,
            "company_visible": isinstance(company, dict),
        }

    def get_company_info(self) -> dict[str, Any]:
        payload = self._company()
        company = payload.get("CompanyInfo") if isinstance(payload.get("CompanyInfo"), dict) else {}
        return {
            "provider": self.provider_name,
            "system": "QuickBooks Online",
            "realm_id": self.db,
            "company": {
                "id": company.get("Id"),
                "name": company.get("CompanyName"),
                "legal_name": company.get("LegalName"),
                "country": company.get("Country"),
            }
            if company
            else None,
        }


class XeroProvider:
    provider_name = "xero"

    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url
        self.db = db.strip()
        self.username = username
        self.password = password
        if not self.db:
            raise ValueError("Xero tenant ID is required.")

    def _organisation(self) -> dict[str, Any]:
        return request_json(
            base_url=self.url,
            method="GET",
            path="/api.xro/2.0/Organisation",
            headers={
                "Authorization": _bearer_auth(self.password),
                "xero-tenant-id": self.db,
            },
        )

    def test_connection(self) -> dict[str, Any]:
        payload = self._organisation()
        organisations = payload.get("Organisations")
        return {
            "provider": self.provider_name,
            "connected": True,
            "system": "Xero",
            "tenant_id": self.db,
            "organisation_visible": isinstance(organisations, list) and bool(organisations),
        }

    def get_company_info(self) -> dict[str, Any]:
        payload = self._organisation()
        organisations = payload.get("Organisations") if isinstance(payload.get("Organisations"), list) else []
        first = organisations[0] if organisations and isinstance(organisations[0], dict) else {}
        return {
            "provider": self.provider_name,
            "system": "Xero",
            "tenant_id": self.db,
            "organisation": {
                "id": first.get("OrganisationID"),
                "name": first.get("Name"),
                "legal_name": first.get("LegalName"),
                "base_currency": first.get("BaseCurrency"),
                "country": first.get("CountryCode"),
            }
            if first
            else None,
        }
