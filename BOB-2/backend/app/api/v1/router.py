from fastapi import APIRouter, Depends

from app.api.v1.account_access import router as account_access_router
from app.api.v1.accounting_ai import router as accounting_ai_router
from app.api.v1.accounting_command_router import router as accounting_command_router
from app.api.v1.accounting_intelligence import router as accounting_intelligence_router
from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bank_posting_v2 import router as bank_posting_v2_router
from app.api.v1.bank_reconciliation_compat import router as bank_reconciliation_compat_router
from app.api.v1.bank_reconciliation_entry_suggestions import router as bank_reconciliation_entry_suggestions_router
from app.api.v1.bank_reconciliation_hardening import router as bank_reconciliation_hardening_router
from app.api.v1.bank_rule_entry_suggestions import router as bank_rule_entry_suggestions_router
from app.api.v1.bank_rule_tax import router as bank_rule_tax_router
from app.api.v1.bank_rules import router as bank_rules_router
from app.api.v1.chat_journal_lookup import router as chat_journal_lookup_router
from app.api.v1.chat_spreadsheet_intent_guard import router as chat_spreadsheet_intent_guard_router
from app.api.v1.communication_tools import router as communication_tools_router
from app.api.v1.daily_bank_review import router as daily_bank_review_router
from app.api.v1.erp_catalog import router as erp_catalog_router
from app.api.v1.erp_connections import router as erp_connections_router
from app.api.v1.erp_document_parsing import router as erp_document_parsing_router
from app.api.v1.erp_documents import router as erp_documents_router
from app.api.v1.erp_monetary_legacy import router as erp_monetary_legacy_router
from app.api.v1.erp_partners import router as erp_partners_router
from app.api.v1.erp_telegram_config import router as erp_telegram_config_router
from app.api.v1.journal import router as journal_router
from app.api.v1.journal_entry_actions import router as journal_entry_actions_router
from app.api.v1.llm_admin import router as llm_admin_router
from app.api.v1.mfa import router as mfa_router
from app.api.v1.system import router as system_router
from app.api.v1.telegram_admin import router as telegram_admin_router
from app.api.v1.telegram_approvals import router as telegram_approvals_router
from app.api.v1.telegram_authorizations import router as telegram_authorizations_router
from app.security.dependencies import enforce_financial_route_permission

api_router = APIRouter()
financial_access = [Depends(enforce_financial_route_permission)]

api_router.include_router(system_router, prefix="/system", tags=["System"])
api_router.include_router(auth_router, prefix="/auth", tags=["Security"])
api_router.include_router(account_access_router, prefix="/auth", tags=["Account Access"])
api_router.include_router(mfa_router, prefix="/auth", tags=["Multi-Factor Authentication"])
api_router.include_router(journal_router, prefix="/journal", tags=["Journal Entries"])
api_router.include_router(telegram_admin_router, prefix="/telegram", tags=["Telegram Administration"])
api_router.include_router(telegram_authorizations_router, prefix="/telegram", tags=["Telegram Authorizations"])
api_router.include_router(telegram_approvals_router, prefix="/telegram", tags=["Telegram Approvals"])
api_router.include_router(llm_admin_router, prefix="/llm", tags=["External LLM Administration"])
api_router.include_router(communication_tools_router, prefix="/communication-tools", tags=["Communication Tools"])

# The centralized dependency is method-aware: reads require view_financials,
# mutations require create_entries by default, settings require manage_settings,
# uploads require upload_documents, audit actions require review_entries,
# approval decisions require approve_actions, and ERP posting requires post_odoo_entries.
api_router.include_router(erp_partners_router, prefix="/erp", tags=["ERP Partners"], dependencies=financial_access)
api_router.include_router(bank_reconciliation_compat_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(bank_reconciliation_hardening_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(bank_rule_entry_suggestions_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(bank_reconciliation_entry_suggestions_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(bank_rules_router, prefix="/erp", tags=["BOB Bank Rules"], dependencies=financial_access)
api_router.include_router(bank_rule_tax_router, prefix="/erp", tags=["BOB Bank Rule Taxes"], dependencies=financial_access)
api_router.include_router(daily_bank_review_router, prefix="/erp", tags=["ERP Daily Bank Audit Workflow"], dependencies=financial_access)
api_router.include_router(accounting_command_router, prefix="/erp", tags=["ERP Accounting Command Brain"], dependencies=financial_access)
api_router.include_router(chat_spreadsheet_intent_guard_router, prefix="/erp", tags=["ERP Smart Chat Intent Guard"], dependencies=financial_access)
api_router.include_router(chat_journal_lookup_router, prefix="/erp", tags=["ERP Smart Chat Journal Lookup"], dependencies=financial_access)
api_router.include_router(erp_connections_router, prefix="/erp", tags=["ERP Connections"], dependencies=financial_access)
api_router.include_router(erp_documents_router, prefix="/erp", tags=["ERP Documents"], dependencies=financial_access)
api_router.include_router(erp_document_parsing_router, prefix="/erp", tags=["ERP Document Parsing"], dependencies=financial_access)
api_router.include_router(erp_catalog_router, prefix="/erp", tags=["ERP Catalog"], dependencies=financial_access)
api_router.include_router(erp_telegram_config_router, prefix="/erp", tags=["ERP Telegram Compatibility"], dependencies=financial_access)
api_router.include_router(erp_monetary_legacy_router, prefix="/erp", tags=["ERP Fixed-Point Monetary Compatibility"], dependencies=financial_access)
api_router.include_router(journal_entry_actions_router, prefix="/erp", tags=["ERP Journal Entry Actions"], dependencies=financial_access)
api_router.include_router(bank_posting_v2_router, prefix="/erp", tags=["ERP Bank Posting"], dependencies=financial_access)
api_router.include_router(accounting_ai_router, prefix="/accounting-ai", tags=["Accounting AI Matching"], dependencies=financial_access)
api_router.include_router(accounting_intelligence_router, prefix="/accounting-intelligence", tags=["Accounting Intelligence Learning"], dependencies=financial_access)
api_router.include_router(agents_router, prefix="/agents", tags=["GMAWS Accounting Agents"], dependencies=financial_access)
