from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.accounting_command_brain import apply_accounting_command
from app.api.v1.chat_spreadsheet_intent_guard import guarded_chat_spreadsheet
from app.api.v1.erp import ChatSpreadsheetRequest
from app.db.database import get_db

router = APIRouter()


@router.post("/chat-spreadsheet")
def accounting_command_chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    """Accounting command brain runs before the legacy LLM spreadsheet chat.

    This prevents accounting instructions from being sent directly to the LLM JSON
    formatter where broken JSON such as "Unterminated string" can leak back to the UI.
    """
    command_result = apply_accounting_command(payload.prompt or "", payload)
    if command_result is not None:
        return command_result

    return guarded_chat_spreadsheet(payload=payload, db_session=db_session)
