"""Immutable accounting-system catalog separated from provider implementations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ERPProviderDefinition:
    key: str
    display_name: str
    category: str
    market: str
    implemented: bool
    description: str

    def public_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "category": self.category,
            "market": self.market,
            "implemented": self.implemented,
            "description": self.description,
        }


ERP_PROVIDER_CATALOG = (
    ERPProviderDefinition("odoo", "Odoo ERP 16–19", "ERP", "Saudi Arabia / Global", True, "موصل XML-RPC كامل للحسابات والقيود والاكتشاف."),
    ERPProviderDefinition("sap_s4hana", "SAP S/4HANA", "Enterprise ERP", "Saudi Arabia / Global", False, "يتطلب موصل SAP OData وخطة صلاحيات مستقلة."),
    ERPProviderDefinition("oracle_fusion", "Oracle Fusion Cloud ERP", "Enterprise ERP", "Saudi Arabia / Global", False, "يتطلب موصل Oracle REST واعتماد OAuth منفصل."),
    ERPProviderDefinition("dynamics_365", "Microsoft Dynamics 365", "Enterprise ERP", "Saudi Arabia / Global", False, "يتطلب موصل Microsoft Dataverse وOAuth."),
    ERPProviderDefinition("zoho_books", "Zoho Books", "Cloud Accounting", "Saudi Arabia / Global", False, "يتطلب موصل Zoho Books OAuth ومواءمة ضريبة القيمة المضافة."),
    ERPProviderDefinition("qoyod", "Qoyod قيود", "Saudi Cloud Accounting", "Saudi Arabia", False, "يتطلب اتفاقية API وموصلًا سعوديًا مخصصًا."),
    ERPProviderDefinition("daftra", "Daftra دفترة", "Cloud ERP", "Saudi Arabia / MENA", False, "يتطلب موصل Daftra API مخصصًا."),
    ERPProviderDefinition("quickbooks", "QuickBooks Online", "Cloud Accounting", "Global", False, "يتطلب موصل Intuit OAuth ومواءمة الحسابات."),
)


def public_erp_provider_catalog() -> list[dict[str, object]]:
    return [provider.public_dict() for provider in ERP_PROVIDER_CATALOG]
