from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.dependencies import get_current_token_payload
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
    organization_id: int | None = Field(default=None, gt=0)
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
            "external_llm_default": "disabled",
            "external_llm_requirements": [
                "global kill-switch approval",
                "tenant administrator opt-in",
                "current DPA acknowledgement",
                "approved provider/model/purpose",
                "redaction and data minimization",
                "pre-disclosure audit event",
            ],
            "purpose": "Assist accountants and auditors without bypassing review controls.",
        },
    }


@router.post("/run-accounting-workflow")
def run_accounting_workflow(
    request: Request,
    workflow_request: RunAccountingWorkflowRequest,
    db: Session = Depends(get_db),
    token_payload: dict = Depends(get_current_token_payload),
):
    organization_id = token_payload.get("organization_id")
    user_id = token_payload.get("user_id")
    if not isinstance(organization_id, int) or organization_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not assigned to an active organization.",
        )
    if not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The authenticated user identity is incomplete.",
        )
    if (
        workflow_request.organization_id is not None
        and workflow_request.organization_id != organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organization accounting analysis is not allowed.",
        )

    try:
        return AccountingMultiAgentOrchestrator().run(
            text=workflow_request.text,
            source_type=workflow_request.source_type,
            organization_id=organization_id,
            user_id=user_id,
            db_session=db,
            request_id=getattr(request.state, "request_id", "unknown"),
            language=workflow_request.language,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The accounting workflow could not be completed.",
        ) from exc
