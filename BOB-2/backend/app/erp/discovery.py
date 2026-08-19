import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.erp.base import ERPDiscoveryProvider
from app.security.tenant_scope import current_organization_id

logger = logging.getLogger(__name__)

STORAGE_DIR = settings.storage_path / "financial_kb"


def _kb_file_path() -> Path:
    organization_id = current_organization_id(required=True)
    assert organization_id is not None
    return STORAGE_DIR / f"organization_{organization_id}.json"


_DISCOVERY_METHODS = (
    "get_company_info",
    "discover_accounts",
    "discover_journals",
    "discover_taxes",
    "discover_partners",
    "discover_analytic_accounts",
    "discover_products",
    "discover_employees",
)


def _supports_discovery(provider: Any) -> bool:
    # Checked by method presence rather than `isinstance(provider,
    # ERPDiscoveryProvider)`: the Protocol also declares provider_name/url/db,
    # which older structural test doubles predate. Method presence is the
    # actual discovery capability that matters here.
    return all(callable(getattr(provider, name, None)) for name in _DISCOVERY_METHODS)


def run_discovery_orchestrator(provider: ERPDiscoveryProvider) -> dict[str, Any]:
    if not _supports_discovery(provider):
        provider_name = getattr(provider, "provider_name", type(provider).__name__)
        raise ValueError(
            f"ERP provider '{provider_name}' does not support structure discovery "
            "(chart of accounts, journals, taxes, partners, cost centers, products, "
            "employees). Discovery is currently only available for the 'odoo' provider."
        )

    organization_id = current_organization_id(required=True)
    assert organization_id is not None
    logger.info("Starting tenant-scoped ERP Discovery Engine orchestrator.")

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    accounts = provider.discover_accounts()
    journals = provider.discover_journals()
    taxes = provider.discover_taxes()
    partners = provider.discover_partners()
    cost_centers = provider.discover_analytic_accounts()
    products = provider.discover_products()
    employees = provider.discover_employees()

    company_info_dict = provider.get_company_info()
    companies = company_info_dict.get("companies", [])

    kb_data = {
        "metadata": {
            "organization_id": organization_id,
            # Older structural test doubles predate the explicit capability
            # metadata. Preserve compatibility while concrete providers expose
            # their own stable name.
            "provider": getattr(provider, "provider_name", "odoo"),
            "url": provider.url,
            "db": provider.db,
            "companies": companies,
        },
        "accounts": accounts,
        "journals": journals,
        "taxes": taxes,
        "partners": partners,
        "cost_centers": cost_centers,
        "products": products,
        "employees": employees,
    }

    destination = _kb_file_path()
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(STORAGE_DIR),
        prefix=f"organization_{organization_id}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(kb_data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)

    logger.info(
        "Tenant financial knowledge base stored successfully for organization %s.",
        organization_id,
    )
    return {
        "success": True,
        "organization_id": organization_id,
        "counts": {
            "accounts": len(accounts),
            "journals": len(journals),
            "taxes": len(taxes),
            "partners": len(partners),
            "cost_centers": len(cost_centers),
            "products": len(products),
            "employees": len(employees),
        },
    }


def load_financial_kb() -> dict[str, Any] | None:
    organization_id = current_organization_id(required=True)
    path = _kb_file_path()
    if not path.exists() or path.is_symlink():
        return None

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        logger.error(
            "Failed to read tenant financial knowledge base for organization %s: %s",
            organization_id,
            type(exc).__name__,
        )
        return None

    metadata = data.get("metadata") if isinstance(data, dict) else None
    if not isinstance(metadata, dict) or metadata.get("organization_id") != organization_id:
        logger.error("Tenant financial knowledge base identity mismatch.")
        return None
    return data
