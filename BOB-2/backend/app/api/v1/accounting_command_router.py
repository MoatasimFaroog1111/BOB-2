from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.accounting_command_brain import apply_accounting_command
from app.api.v1.chat_spreadsheet_intent_guard import guarded_chat_spreadsheet
from app.api.v1.erp_spreadsheet import (
    ChatSpreadsheetRequest,
    chat_spreadsheet as llm_spreadsheet_assistant,
)
from app.api.v1.hybrid_account_partner_search import try_hybrid_account_partner_search
from app.api.v1.hybrid_global_account_search_v2 import (
    try_hybrid_global_account_search_v2,
)
from app.api.v1.natural_language_command_model import execute_natural_language_command
from app.api.v1.spreadsheet_prompt_routing_policy import (
    SpreadsheetPromptRoute,
    spreadsheet_prompt_routing_policy,
)
from app.db.database import get_db

router = APIRouter()


def _run_command_pipeline(
    payload: ChatSpreadsheetRequest,
    db_session: Session,
):
    """Run only the components that are allowed to interpret execution commands."""
    nlu_result = execute_natural_language_command(
        payload.prompt or "",
        payload,
        db_session=db_session,
    )
    if nlu_result is not None:
        return nlu_result

    command_result = apply_accounting_command(payload.prompt or "", payload)
    if command_result is not None:
        return command_result

    return guarded_chat_spreadsheet(payload=payload, db_session=db_session)


@router.post("/chat-spreadsheet")
def accounting_command_chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    """Route spreadsheet prompts by responsibility before executing an application component.

    Routing order:
    1. Read-only questions and analytical prompts -> LLM Spreadsheet Assistant directly.
    2. Explicit mutation/execution prompts -> Accounting Command Model pipeline.
    3. Unclassified prompts retain the existing local-search and command fallbacks.

    The routing policy is intentionally separate from this HTTP adapter so that intent
    classification can evolve and be tested without coupling it to FastAPI, Odoo, or the LLM
    transport. Free-form model text still cannot directly write to Odoo.
    """
    routing = spreadsheet_prompt_routing_policy.decide(payload.prompt or "")

    if routing.route == SpreadsheetPromptRoute.ASSISTANT:
        # Bypass the legacy command guard here on purpose: read-only analytical questions can
        # contain words such as "تعديل" inside phrases like "بدون تعديل الجدول". Sending them
        # through the command guard would recreate the false mutation classification.
        return llm_spreadsheet_assistant(payload=payload, db_session=db_session)

    if routing.route == SpreadsheetPromptRoute.COMMAND:
        return _run_command_pipeline(payload, db_session)

    hybrid_result = try_hybrid_account_partner_search(
        payload=payload,
        db_session=db_session,
    )
    if hybrid_result is not None:
        return hybrid_result

    global_search_result = try_hybrid_global_account_search_v2(
        payload=payload,
        db_session=db_session,
    )
    if global_search_result is not None:
        return global_search_result

    return _run_command_pipeline(payload, db_session)
