import json
import os
import logging
from typing import Any
from app.core.config import settings
from app.erp.providers.odoo import OdooProvider

logger = logging.getLogger(__name__)

# Path to local knowledge base file
STORAGE_DIR = str(settings.storage_path)
KB_FILE_PATH = os.path.join(STORAGE_DIR, "financial_kb_org_1.json")


def run_discovery_orchestrator(provider: OdooProvider) -> dict[str, Any]:
    logger.info("Starting ERP Discovery Engine orchestrator...")

    # Ensure storage directory exists
    os.makedirs(STORAGE_DIR, exist_ok=True)

    # Run Odoo discovery methods
    accounts = provider.discover_accounts()
    journals = provider.discover_journals()
    taxes = provider.discover_taxes()
    partners = provider.discover_partners()
    cost_centers = provider.discover_analytic_accounts()
    products = provider.discover_products()
    employees = provider.discover_employees()

    # Discovered metadata
    company_info_dict = provider.get_company_info()
    companies = company_info_dict.get("companies", [])

    # Structure the Financial Knowledge Base
    kb_data = {
        "metadata": {
            "provider": "odoo",
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

    # Save to storage file
    with open(KB_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(kb_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Financial Knowledge Base stored successfully at {KB_FILE_PATH}")

    return {
        "success": True,
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
    if not os.path.exists(KB_FILE_PATH):
        return None

    try:
        with open(KB_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read Financial Knowledge Base: {e}")
        return None
