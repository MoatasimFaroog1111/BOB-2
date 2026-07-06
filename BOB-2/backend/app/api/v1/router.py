from fastapi import APIRouter
from app.api.v1.system import router as system_router
from app.api.v1.auth import router as auth_router
from app.api.v1.erp_partners import router as erp_partners_router
from app.api.v1.bank_reconciliation_compat import router as bank_reconciliation_compat_router
from app.api.v1.bank_reconciliation_hardening import router as bank_reconciliation_hardening_router
from app.api.v1.bank_reconciliation_entry_suggestions import router as bank_reconciliation_entry_suggestions_router
from app.api.v1.erp import router as erp_router
from app.api.v1.bank_posting_v2 import router as bank_posting_v2_router
from app.api.v1.accounting_ai import router as accounting_ai_router
from app.api.v1.agents import router as agents_router

api_router = APIRouter()
api_router.include_router(system_router, prefix="/system", tags=["System"])
api_router.include_router(auth_router, prefix="/auth", tags=["Security"])
api_router.include_router(erp_partners_router, prefix="/erp", tags=["ERP Partners"])
api_router.include_router(bank_reconciliation_compat_router, prefix="/erp", tags=["ERP Bank Reconciliation"])
api_router.include_router(bank_reconciliation_hardening_router, prefix="/erp", tags=["ERP Bank Reconciliation"])
api_router.include_router(bank_reconciliation_entry_suggestions_router, prefix="/erp", tags=["ERP Bank Reconciliation"])
api_router.include_router(erp_router, prefix="/erp", tags=["ERP"])
api_router.include_router(bank_posting_v2_router, prefix="/erp", tags=["ERP Bank Posting"])
api_router.include_router(accounting_ai_router, prefix="/accounting-ai", tags=["Accounting AI Matching"])
api_router.include_router(agents_router, prefix="/agents", tags=["GMAWS Accounting Agents"])
