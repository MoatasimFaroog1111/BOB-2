import hmac
import os
from datetime import date
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

router = APIRouter()
security = HTTPBearer(auto_error=False)

# Temporary storage retained for compatibility. This service must be migrated to
# PostgreSQL with organization scoping and an immutable audit trail before use
# with real accounting data.
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


def require_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    expected = os.getenv("GUARDIAN_SERVICE_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Journal service authentication is not configured",
        )
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/entries", dependencies=[Depends(require_service_token)])
def get_journal_entries():
    return JOURNAL_DB
