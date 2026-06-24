from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.ai_accounting import AIDecisionAuditLog
from app.services.accounting_ai import AccountingAIMatchingService

router = APIRouter()


class AnalyzeAccountingTextRequest(BaseModel):
    text: str = Field(..., min_length=8)
    source_type: Literal["invoice", "receipt", "payment_voucher", "purchase_order", "bank_statement", "journal_entry", "trial_balance", "vendor_bill", "ocr_text", "manual_text"] = "manual_text"
    source_reference: str | None = None
    document_id: int | None = None
    organization_id: int = 1


class DecisionStatusRequest(BaseModel):
    status: Literal["approved", "rejected", "pending", "draft"]
    organization_id: int = 1


def _match_to_dict(match) -> dict[str, Any]:
    return {"id": match.id, "match_type": match.match_type, "target_embedding_id": match.target_embedding_id, "confidence_score": match.confidence_score, "similarity_score": match.similarity_score, "explanation": match.explanation, "status": match.status, "metadata": match.match_metadata}


def _suggestion_to_dict(suggestion) -> dict[str, Any]:
    return {"id": suggestion.id, "status": suggestion.status, "confidence_score": suggestion.confidence_score, "explanation": suggestion.explanation, "debit_account": suggestion.debit_account, "credit_account": suggestion.credit_account, "vat_account": suggestion.vat_account, "payload": suggestion.suggestion_payload}


@router.post("/analyze")
def analyze_accounting_text(payload: AnalyzeAccountingTextRequest, db: Session = Depends(get_db)):
    try:
        result = AccountingAIMatchingService(db).analyze_document(text=payload.text, source_type=payload.source_type, organization_id=payload.organization_id, document_id=payload.document_id, source_reference=payload.source_reference)
        return {"status": "success", "embedding": {"id": result.embedding.id, "model": result.embedding.embedding_model, "dimension": result.embedding.embedding_dimension, "confidence_score": result.embedding.confidence_score, "classification": result.embedding.classification, "text_preview": result.embedding.text_preview}, "suggested_matches": [_match_to_dict(m) for m in result.matches], "journal_entry_suggestion": _suggestion_to_dict(result.suggestion), "audit_safe": {"auto_posted_to_erp": False, "approval_required": True}}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/matches/{match_id}/status")
def update_match_status(match_id: int, payload: DecisionStatusRequest, db: Session = Depends(get_db)):
    try:
        return AccountingAIMatchingService(db).update_decision_status("match", match_id, payload.status, payload.organization_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/suggestions/{suggestion_id}/status")
def update_suggestion_status(suggestion_id: int, payload: DecisionStatusRequest, db: Session = Depends(get_db)):
    try:
        return AccountingAIMatchingService(db).update_decision_status("suggestion", suggestion_id, payload.status, payload.organization_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/audit-log")
def list_ai_audit_log(db: Session = Depends(get_db), organization_id: int = 1, limit: int = 50):
    rows = db.query(AIDecisionAuditLog).filter(AIDecisionAuditLog.organization_id == organization_id).order_by(AIDecisionAuditLog.created_at.desc()).limit(min(limit, 200)).all()
    return {"status": "success", "items": [{"id": r.id, "decision_type": r.decision_type, "entity_type": r.entity_type, "entity_id": r.entity_id, "confidence_score": r.confidence_score, "explanation": r.explanation, "payload": r.payload, "created_at": r.created_at.isoformat()} for r in rows]}
