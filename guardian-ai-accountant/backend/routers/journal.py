from datetime import date
from typing import List, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()

JOURNAL_DB = []


class JournalLine(BaseModel):
    account: str
    debit: float = Field(default=0, ge=0)
    credit: float = Field(default=0, ge=0)
    description: str = ""


class JournalEntry(BaseModel):
    date: date
    reference: str
    memo: str
    lines: List[JournalLine]
    status: Literal["draft", "posted"] = "draft"


@router.get("/entries")
def get_journal_entries():
    return JOURNAL_DB
