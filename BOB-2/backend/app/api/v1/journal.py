from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.money import (
    MoneyValidationError,
    NonNegativeMoney,
    canonical_money_lines,
    money_to_str,
    validate_balanced_lines,
)
from app.db.database import get_db
from app.models.core import AuditLog, JournalEntryRecord, User
from app.security.dependencies import require_permission

router = APIRouter()


class JournalLine(BaseModel):
    account: str = Field(..., min_length=1, max_length=255)
    debit: NonNegativeMoney = Decimal("0.00")
    credit: NonNegativeMoney = Decimal("0.00")
    description: str = Field(default="", max_length=1000)


class JournalEntryCreate(BaseModel):
    date: date
    reference: str = Field(..., min_length=1, max_length=255)
    memo: str = Field(default="", max_length=4000)
    lines: list[JournalLine] = Field(..., min_length=2, max_length=200)
    status: Literal["draft"] = "draft"


class JournalEntryResponse(BaseModel):
    id: int
    date: date
    reference: str
    memo: str
    status: str
    lines: list[dict]
    total_debit: str
    total_credit: str


def _resolve_user(db: Session, current_user: dict) -> User:
    user_id = current_user.get("user_id")
    query = db.query(User)
    user = query.filter(User.id == user_id).first() if user_id else None
    if user is None:
        user = query.filter(User.email == current_user.get("sub")).first()
    if not user or not user.is_active or user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user is not associated with an active organization.",
        )
    return user


def _serialize(entry: JournalEntryRecord) -> JournalEntryResponse:
    return JournalEntryResponse(
        id=entry.id,
        date=entry.entry_date,
        reference=entry.reference,
        memo=entry.memo,
        status=entry.status,
        lines=entry.lines,
        total_debit=money_to_str(entry.total_debit),
        total_credit=money_to_str(entry.total_credit),
    )


@router.get("/entries", response_model=list[JournalEntryResponse])
def get_journal_entries(
    limit: int = Query(default=200, ge=1, le=500),
    current_user: dict = Depends(require_permission("view_financials")),
    db: Session = Depends(get_db),
):
    user = _resolve_user(db, current_user)
    entries = (
        db.query(JournalEntryRecord)
        .filter(JournalEntryRecord.organization_id == user.organization_id)
        .order_by(JournalEntryRecord.entry_date.desc(), JournalEntryRecord.id.desc())
        .limit(limit)
        .all()
    )
    return [_serialize(entry) for entry in entries]


@router.post("/entries", response_model=JournalEntryResponse, status_code=201)
def create_journal_entry(
    payload: JournalEntryCreate,
    current_user: dict = Depends(require_permission("create_entries")),
    db: Session = Depends(get_db),
):
    user = _resolve_user(db, current_user)
    raw_lines = [line.model_dump() for line in payload.lines]
    try:
        total_debit, total_credit = validate_balanced_lines(raw_lines)
        stored_lines = canonical_money_lines(raw_lines)
    except MoneyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    entry = JournalEntryRecord(
        organization_id=user.organization_id,
        created_by_user_id=user.id,
        entry_date=payload.date,
        reference=payload.reference.strip(),
        memo=payload.memo.strip(),
        status="draft",
        lines=stored_lines,
        total_debit=total_debit,
        total_credit=total_credit,
    )
    db.add(entry)
    db.flush()
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action="journal_entry_created",
            entity_type="journal_entry",
            entity_id=str(entry.id),
            details={
                "reference": entry.reference,
                "total_debit": money_to_str(total_debit),
                "total_credit": money_to_str(total_credit),
                "status": entry.status,
                "money_scale": 2,
            },
        )
    )
    db.commit()
    db.refresh(entry)
    return _serialize(entry)
