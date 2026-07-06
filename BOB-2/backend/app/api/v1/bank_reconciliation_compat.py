from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.bank_reconciliation_hardening import bank_reconciliation as hardened_bank_reconciliation
from app.db.database import get_db

router = APIRouter()


@router.post("/bank-reconciliation")
async def bank_reconciliation_compat(
    statement: UploadFile = File(...),
    db: Session = Depends(get_db),
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
    company_id: Optional[int] = Form(None),
    bank_journal_id: Optional[int] = Form(None),
):
    try:
        return await hardened_bank_reconciliation(
            statement=statement,
            db=db,
            date_from=date_from,
            date_to=date_to,
            company_id=company_id,
            bank_journal_id=bank_journal_id,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND and "No active ERP connection" in str(exc.detail):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail) from exc
        raise
