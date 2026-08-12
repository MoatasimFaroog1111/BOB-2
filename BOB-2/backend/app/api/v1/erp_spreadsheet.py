"""Spreadsheet assistant application component.

The public HTTP route is owned by accounting_command_router. This module owns the
request contract and the read/analysis assistant orchestration. BOB Bank Rules are the
classification source of truth; Odoo supplies live accounting reference catalogues only.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.tenant_scope import current_organization_id
from app.services.bank_rule_assistant_context import bank_rule_assistant_context_provider
from app.services.llm_service import chat as llm_chat
from app.services.tenant_erp_service import tenant_erp_resolver

logger = logging.getLogger(__name__)


class SheetPayload(BaseModel):
    id: str
    name: str
    gridData: List[List[str]]
    rowCount: int
    colCount: int


class ChatSpreadsheetRequest(BaseModel):
    prompt: str
    sheets: List[SheetPayload]
    active_sheet_id: str
    company_id: Optional[int] = 1


def _active_sheet(payload: ChatSpreadsheetRequest) -> SheetPayload:
    for sheet in payload.sheets:
        if sheet.id == payload.active_sheet_id:
            return sheet
    if payload.sheets:
        return payload.sheets[0]
    raise HTTPException(status_code=422, detail="At least one spreadsheet is required.")


def _load_odoo_reference_context(db_session: Session, organization_id: int) -> tuple[str, str]:
    """Load live Odoo accounts/partners without exposing ERP credentials to this component."""
    try:
        _connection, erp = tenant_erp_resolver.resolve(db_session, organization_id)
        partners = erp.execute_kw(
            "res.partner",
            "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "limit": 2000},
        )
        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [[]],
            {"fields": ["id", "code", "name", "account_type"], "limit": 2000},
        )
        partners_text = "\n".join(
            f"- ID: {partner['id']}, Name: {partner['name']}"
            for partner in partners
            if partner.get("id") and partner.get("name")
        )
        accounts_text = "\n".join(
            f"- ID: {account['id']}, Code: {account.get('code')}, Name: {account.get('name')}, Type: {account.get('account_type')}"
            for account in accounts
            if account.get("id")
        )
        return accounts_text, partners_text
    except Exception as exc:
        logger.info("[Spreadsheet Agent] Odoo reference catalogue unavailable: %s", exc)
        return (
            "Odoo account catalogue is currently unavailable. Do not invent account IDs/codes.",
            "Odoo partner catalogue is currently unavailable. Do not invent partner identities.",
        )


def _system_prompt() -> str:
    return (
        "You are the Smart Accountant spreadsheet analysis assistant. Return ONLY a valid JSON object.\n"
        "BOB Bank Rules are the sole source of truth for bank-transaction classification rules. "
        "Odoo is the source of truth only for referenced journals, accounts, partners, and analytic accounts.\n\n"
        "Required JSON fields:\n"
        "- message: string.\n"
        "- grid_data: optional rectangular list[list[string]] only when the user explicitly requests spreadsheet modification.\n"
        "- active_sheet_name: optional string.\n"
        "- create_sheet: optional {name, grid_data}.\n"
        "- delete_sheet_id: optional string.\n\n"
        "NON-NEGOTIABLE CONTROLS:\n"
        "1. If the user asks a question, requests analysis/explanation/listing, or says without modifying/بدون تعديل, "
        "answer in message only and OMIT all spreadsheet mutation fields.\n"
        "2. Never invent an account, account code, partner, analytic account, journal, Bank Rule, or Rule match.\n"
        "3. Never use or suggest a suspense/default/fallback account merely because no rule matched. "
        "If no approved BOB Bank Rule matches, state that the transaction is unresolved and requires a rule or human review.\n"
        "4. For bank classification, use ONLY the APPROVED ACTIVE BOB Bank Rules supplied in the context. "
        "Evaluate every condition in a rule as AND. Lower numeric priority wins. If two matching rules have the same top priority, "
        "treat the result as ambiguous and do not select an account.\n"
        "5. When a BOB rule matches, use the exact target AccountCode/AccountName and report the Rule name/version when asked.\n"
        "6. Odoo account/partner matching must use exact records from the supplied live catalogue. Translation or typo tolerance may "
        "help identify a candidate, but if identity is uncertain, ask for clarification rather than inventing an ID/code.\n"
        "7. Double-entry must remain balanced. Never manufacture an offset account to force balance. If the correct counterpart is unresolved, "
        "keep it unresolved and explain what is missing.\n"
        "8. Do not post, approve, or claim that anything was posted to Odoo. This assistant only analyzes or prepares spreadsheet content.\n"
        "9. Respond in professional Arabic when the user writes Arabic; otherwise respond in the user's language.\n"
        "10. Correct minor spelling errors in explanations, but preserve source transaction evidence.\n"
    )


def chat_spreadsheet(
    payload: ChatSpreadsheetRequest,
    db_session: Session = Depends(get_db),
):
    active_sheet = _active_sheet(payload)
    organization_id = current_organization_id(required=True)

    # Draft and superseded rules are intentionally excluded by the context provider.
    bob_rules = bank_rule_assistant_context_provider.load(
        db_session,
        organization_id=organization_id,
        limit=500,
    )
    bank_rules_text = bank_rule_assistant_context_provider.format_for_llm(bob_rules)
    accounts_text, partners_text = _load_odoo_reference_context(db_session, organization_id)

    user_prompt = (
        f"User Request: {json.dumps(payload.prompt, ensure_ascii=False)}\n\n"
        f"Active Sheet:\n"
        f"- Name: {json.dumps(active_sheet.name, ensure_ascii=False)}\n"
        f"- ID: {json.dumps(active_sheet.id, ensure_ascii=False)}\n"
        f"- Rows: {active_sheet.rowCount}, Columns: {active_sheet.colCount}\n"
        f"- Grid Data: {json.dumps(active_sheet.gridData, ensure_ascii=False)}\n\n"
        f"Available Sheets: {json.dumps([{'id': sheet.id, 'name': sheet.name} for sheet in payload.sheets], ensure_ascii=False)}\n\n"
        "=== APPROVED ACTIVE BOB BANK RULES ===\n"
        f"{bank_rules_text[:20000]}\n\n"
        "=== LIVE ODOO ACCOUNT REFERENCES ===\n"
        f"{accounts_text[:20000]}\n\n"
        "=== LIVE ODOO PARTNER REFERENCES ===\n"
        f"{partners_text[:20000]}\n"
    )

    result = llm_chat(_system_prompt(), user_prompt)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AI provider is unavailable. Configure an approved AI provider in Settings "
                "or enable the configured local LLM runtime."
            ),
        )

    content = result.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        response_obj = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("[Spreadsheet Agent] LLM returned invalid JSON: %s", exc)
        return {
            "message": content,
            "grid_data": None,
            "active_sheet_name": None,
            "create_sheet": None,
            "delete_sheet_id": None,
        }

    if not isinstance(response_obj, dict):
        return {
            "message": str(response_obj),
            "grid_data": None,
            "active_sheet_name": None,
            "create_sheet": None,
            "delete_sheet_id": None,
        }

    # Defensive response shaping. Unknown fields never become implicit actions.
    return {
        "message": str(response_obj.get("message") or ""),
        "grid_data": response_obj.get("grid_data") if isinstance(response_obj.get("grid_data"), list) else None,
        "active_sheet_name": response_obj.get("active_sheet_name") if isinstance(response_obj.get("active_sheet_name"), str) else None,
        "create_sheet": response_obj.get("create_sheet") if isinstance(response_obj.get("create_sheet"), dict) else None,
        "delete_sheet_id": response_obj.get("delete_sheet_id") if isinstance(response_obj.get("delete_sheet_id"), str) else None,
    }
