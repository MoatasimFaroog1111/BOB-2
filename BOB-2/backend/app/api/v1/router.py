from fastapi import APIRouter, Depends

from app.api.v1.accounting_ai import router as accounting_ai_router
from app.api.v1.accounting_command_router import router as accounting_command_router
from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bank_posting_v2 import router as bank_posting_v2_router
from app.api.v1.bank_reconciliation_compat import router as bank_reconciliation_compat_router
from app.api.v1.bank_reconciliation_entry_suggestions import router as bank_reconciliation_entry_suggestions_router
from app.api.v1.bank_reconciliation_hardening import router as bank_reconciliation_hardening_router
from app.api.v1.bank_rule_entry_suggestions import router as bank_rule_entry_suggestions_router
from app.api.v1.chat_journal_lookup import router as chat_journal_lookup_router
from app.api.v1.chat_spreadsheet_intent_guard import router as chat_spreadsheet_intent_guard_router
from app.api.v1.communication_tools import router as communication_tools_router
from app.api.v1.erp import router as erp_router
from app.api.v1.erp_partners import router as erp_partners_router
from app.api.v1.journal import router as journal_router
from app.api.v1.journal_entry_actions import router as journal_entry_actions_router
from app.api.v1.llm_admin import router as llm_admin_router
from app.api.v1.system import router as system_router
from app.api.v1.telegram_admin import router as telegram_admin_router
from app.api.v1.telegram_approvals import router as telegram_approvals_router
from app.api.v1.telegram_authorizations import router as telegram_authorizations_router
from app.security.dependencies import enforce_financial_route_permission

api_router = APIRouter()
financial_access = [Depends(enforce_financial_route_permission)]

api_router.include_router(system_router, prefix="/system", tags=["System"])
api_router.include_router(auth_router, prefix="/auth", tags=["Security"])
api_router.include_router(journal_router, prefix="/journal", tags=["Journal Entries"])
api_router.include_router(
    telegram_admin_router,
    prefix="/telegram",
    tags=["Telegram Administration"],
)
api_router.include_router(
    telegram_authorizations_router,
    prefix="/telegram",
    tags=["Telegram Authorizations"],
)
api_router.include_router(
    telegram_approvals_router,
    prefix="/telegram",
    tags=["Telegram Approvals"],
)
api_router.include_router(
    llm_admin_router,
    prefix="/llm",
    tags=["External LLM Administration"],
)
api_router.include_router(
    communication_tools_router,
    prefix="/communication-tools",
    tags=["Communication Tools"],
)

# The centralized dependency is method-aware: reads require view_financials,
# mutations require create_entries by default, settings require manage_settings,
# uploads require upload_documents, and ERP posting requires post_odoo_entries.
api_router.include_router(erp_partners_router, prefix="/erp", tags=["ERP Partners"], dependencies=financial_access)
api_router.include_router(bank_reconciliation_compat_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(bank_reconciliation_hardening_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(bank_rule_entry_suggestions_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(bank_reconciliation_entry_suggestions_router, prefix="/erp", tags=["ERP Bank Reconciliation"], dependencies=financial_access)
api_router.include_router(accounting_command_router, prefix="/erp", tags=["ERP Accounting Command Brain"], dependencies=financial_access)
api_router.include_router(chat_spreadsheet_intent_guard_router, prefix="/erp", tags=["ERP Smart Chat Intent Guard"], dependencies=financial_access)
api_router.include_router(chat_journal_lookup_router, prefix="/erp", tags=["ERP Smart Chat Journal Lookup"], dependencies=financial_access)
api_router.include_router(erp_router, prefix="/erp", tags=["ERP"], dependencies=financial_access)
api_router.include_router(journal_entry_actions_router, prefix="/erp", tags=["ERP Journal Entry Actions"], dependencies=financial_access)
api_router.include_router(bank_posting_v2_router, prefix="/erp", tags=["ERP Bank Posting"], dependencies=financial_access)
api_router.include_router(accounting_ai_router, prefix="/accounting-ai", tags=["Accounting AI Matching"], dependencies=financial_access)
api_router.include_router(agents_router, prefix="/agents", tags=["GMAWS Accounting Agents"], dependencies=financial_access)
