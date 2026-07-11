from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.accounting_command_brain import apply_accounting_command
from app.api.v1.chat_spreadsheet_intent_guard import guarded_chat_spreadsheet
from app.api.v1.erp import ChatSpreadsheetRequest
from app.api.v1.natural_language_command_model import execute_natural_language_command
from app.db.database import get_db

router = APIRouter()


@router.post("/chat-spreadsheet")
def accounting_command_chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    """Full natural-language command model before legacy spreadsheet chat.

    Routing order:
    1. Natural Language Command Model: LLM structured NLU + deterministic safety overrides.
    2. Existing deterministic Accounting Command Brain fallback.
    3. Existing guarded smart chat / legacy spreadsheet assistant.

    This gives the system a real natural-language command layer without allowing free-form
    LLM text to directly write to Odoo or leak broken JSON to the UI.
    """
    nlu_result = execute_natural_language_command(payload.prompt or "", payload, db_session=db_session)
    if nlu_result is not None:
        return nlu_result

    command_result = apply_accounting_command(payload.prompt or "", payload)
    if command_result is not None:
        return command_result

    return guarded_chat_spreadsheet(payload=payload, db_session=db_session)
