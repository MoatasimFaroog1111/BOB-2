from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.multi_agent_accounting import AccountingMultiAgentOrchestrator, SOURCE_TYPES

router = APIRouter()


class RunAccountingWorkflowRequest(BaseModel):
    text: str = Field(..., min_length=8)
    source_type: Literal[
        "invoice",
        "receipt",
        "payment_voucher",
        "purchase_order",
        "bank_statement",
        "journal_entry",
        "trial_balance",
        "vendor_bill",
        "ocr_text",
        "manual_text",
    ] = "manual_text"
    organization_id: int = 1
    language: Literal["auto", "ar", "en"] = "auto"


@router.get("/capabilities")
def list_agent_capabilities():
    return {
        "status": "success",
        "workflow": "gmaws_inspired_accounting_multi_agent",
        "supported_source_types": sorted(SOURCE_TYPES),
        "agents": [
            {"name": "IntakeAgent", "role": "document classification and language detection"},
            {"name": "DocumentControlAgent", "role": "required accounting evidence check"},
            {"name": "TaxAgent", "role": "KSA VAT signal review"},
            {"name": "JournalAgent", "role": "draft journal-entry suggestion"},
            {"name": "ReviewerAgent", "role": "audit safety and approval gate"},
        ],
        "safety": {
            "auto_posting_to_erp": False,
            "approval_required": True,
            "purpose": "Assist accountants and auditors without bypassing review controls.",
        },
    }


@router.post("/run-accounting-workflow")
def run_accounting_workflow(payload: RunAccountingWorkflowRequest):
    try:
        return AccountingMultiAgentOrchestrator().run(
            text=payload.text,
            source_type=payload.source_type,
            organization_id=payload.organization_id,
            language=payload.language,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
