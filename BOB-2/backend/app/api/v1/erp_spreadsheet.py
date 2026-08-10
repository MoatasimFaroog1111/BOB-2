"""Legacy spreadsheet assistant application component.

The public HTTP route is owned by accounting_command_router; this module owns
only the request contract and fallback orchestration used by intent guards.
"""

import json
import logging
from typing import List, Optional

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value
from app.security.tenant_scope import current_organization_id
from app.services.llm_service import chat as llm_chat

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

def chat_spreadsheet(payload: ChatSpreadsheetRequest, db_session: Session = Depends(get_db)):
    # Find active sheet
    active_sheet = None
    for s in payload.sheets:
        if s.id == payload.active_sheet_id:
            active_sheet = s
            break
    if not active_sheet:
        active_sheet = payload.sheets[0]

    # Fetch dynamic Odoo accounts, partners, and bank rules if connection is active
    odoo_accounts = []
    odoo_partners = []
    odoo_bank_rules = []
    odoo_connected = False
    
    try:
        conn = db_session.query(ERPConnection).filter(
            ERPConnection.organization_id == current_organization_id(required=True),
            ERPConnection.is_active == True
        ).first()
        
        if conn:
            secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
            username = secret_data.get("username")
            password = secret_data.get("password")
            
            erp = get_erp_provider(
                provider=conn.provider,
                url=conn.base_url,
                db=conn.database_name or "",
                username=username,
                password=password,
            )
            
            # 1. Resolve Company ID
            users = erp.execute_kw(
                "res.users",
                "search_read",
                [[["login", "=", username]]],
                {"fields": ["company_id"], "limit": 1}
            )
            user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

            # Fetch active partners
            odoo_partners = erp.execute_kw(
                "res.partner",
                "search_read",
                [[["active", "=", True]]],
                {"fields": ["id", "name"], "limit": 2000}
            )
            
            # Fetch active accounts
            odoo_accounts = erp.execute_kw(
                "account.account",
                "search_read",
                [[]],
                {"fields": ["id", "code", "name", "account_type"], "limit": 2000}
            )

            # Fetch active bank rules / reconcile models
            if user_company_id:
                try:
                    reconcile_models = erp.execute_kw(
                        "account.reconcile.model",
                        "search_read",
                        [[["company_id", "=", user_company_id]]],
                        {"fields": ["id", "name", "match_label", "match_label_param", "line_ids"], "order": "sequence"}
                    )
                    
                    all_line_ids = []
                    for model in reconcile_models:
                        line_ids = model.get("line_ids")
                        if line_ids:
                            all_line_ids.extend(line_ids)
                    
                    model_lines = {}
                    if all_line_ids:
                        lines_detail = erp.execute_kw(
                            "account.reconcile.model.line",
                            "search_read",
                            [[["id", "in", list(set(all_line_ids))]]],
                            {"fields": ["id", "account_id", "label"]}
                        )
                        model_lines = {l["id"]: l for l in lines_detail}
                    
                    for model in reconcile_models:
                        m_name = model.get("name")
                        m_label = model.get("match_label")
                        m_param = model.get("match_label_param")
                        line_ids = model.get("line_ids") or []
                        
                        acc_code = ""
                        acc_name = ""
                        line_label = ""
                        if line_ids:
                            first_line_id = line_ids[0]
                            detail = model_lines.get(first_line_id)
                            if detail and detail.get("account_id"):
                                acc_id_val = detail["account_id"]
                                if isinstance(acc_id_val, (list, tuple)):
                                    acc_name = acc_id_val[1]
                                    import re as pyre
                                    m_code = pyre.match(r"^(\d+)", acc_name)
                                    if m_code:
                                        acc_code = m_code.group(1)
                                    else:
                                        acc_code = acc_name
                                else:
                                    acc_code = str(acc_id_val)
                                line_label = detail.get("label") or ""
                        
                        if acc_code:
                            odoo_bank_rules.append({
                                "name": m_name,
                                "match_label": m_label,
                                "match_label_param": m_param,
                                "account_code": acc_code,
                                "account_name": acc_name,
                                "line_label": line_label
                            })
                except Exception as rule_err:
                    logger.info(f"[Spreadsheet Agent] Failed to load reconcile models: {rule_err}")

            odoo_connected = True
            logger.info(f"[Spreadsheet Agent] Successfully loaded {len(odoo_partners)} partners, {len(odoo_accounts)} accounts, and {len(odoo_bank_rules)} bank rules from Odoo.")
    except Exception as e:
        logger.info(f"[Spreadsheet Agent] Failed to fetch Odoo context: {e}")

    # Format Odoo context for LLM
    partners_text = ""
    accounts_text = ""
    bank_rules_text = ""
    if odoo_connected:
        partners_text = "\n".join([f"- ID: {p['id']}, Name: {p['name']}" for p in odoo_partners if p.get('name')])
        accounts_text = "\n".join([f"- Code: {a['code']}, Name: {a['name']}, Type: {a['account_type']}" for a in odoo_accounts])
        bank_rules_text = "\n".join([
            f"- Rule: Name=\"{r['name']}\", MatchLabel={r['match_label']}, Param=\"{r['match_label_param']}\" -> Account={r['account_code']} ({r['account_name']}), Label=\"{r['line_label']}\""
            for r in odoo_bank_rules
        ])
    else:
        partners_text = "No active Odoo connection or could not fetch partners."
        accounts_text = "No active Odoo connection or could not fetch accounts."
        bank_rules_text = "No active Odoo connection or could not fetch bank rules."

    system_prompt = (
        "You are an exceptionally intelligent spreadsheet layout, accounting formatting, and data organizing assistant (intelligent agent).\n"
        "Your job is to help users organize, format, and structure their spreadsheet data. The user wants to format sheets to be ready to register in Odoo.\n"
        "Odoo journal entries require the following standard columns:\n"
        "- Column A (index 0): Account Code / رمز الحساب (e.g. 101001, 102014, 501001, etc.)\n"
        "- Column B (index 1): Description / البيان\n"
        "- Column C (index 2): Debit / مدين\n"
        "- Column D (index 3): Credit / دائن\n"
        "- Column E (index 4): Partner / الشريك\n\n"
        "You can manipulate the active sheet's grid data (a 2D array of strings), rename the active sheet, create sheets, or delete sheets.\n"
        "You must return a JSON object with the following fields:\n"
        "- \"message\": (string) Your response. Explain what you changed or ask clarifying questions if information is missing or ambiguous.\n"
        "- \"grid_data\": (optional, list of list of strings) The updated grid data (matrix of string cells) for the active sheet.\n"
        "- \"active_sheet_name\": (optional, string) The new name of the active sheet.\n"
        "- \"create_sheet\": (optional, object with \"name\" and \"grid_data\") If you need to create a new sheet.\n"
        "- \"delete_sheet_id\": (optional, string) ID of a sheet to delete.\n\n"
        "CRITICAL BEHAVIOR RULES:\n"
        "1. BILINGUAL RESPONSE ALIGNMENT:\n"
        "   - Detect the language of the user's prompt (Arabic or English).\n"
        "   - If the user writes in Arabic, your \"message\" MUST be written in fluent, professional Arabic. All explanations and questions must be in Arabic.\n"
        "   - If the user writes in English, your \"message\" MUST be written in fluent, professional English.\n"
        "   - The spreadsheet grid headers can match the user's language preference or standard accounting terms (e.g. 'رمز الحساب', 'البيان', 'مدين', 'دائن', 'الشريك' for Arabic, or 'Account Code', 'Description', 'Debit', 'Credit', 'Partner' for English).\n\n"
        "2. SPELLING CORRECTION & TYPO TOLERANCE:\n"
        "   - Be extremely robust against human typing errors, misspellings, and translation differences (in both the user query and the sheet data).\n"
        "   - Understand what the user wants even with typos or incomplete sentences. Correct any spelling errors in the sheet labels/descriptions.\n\n"
        "3. INTELLIGENT ODOO RECORD MATCHING:\n"
        "   - You are provided with the active list of Odoo Partners and Odoo Accounts (code, name, type).\n"
        "   - Compare the partner names and account descriptions/names referenced by the user (or already in the sheet) against these Odoo lists.\n"
        "   - If a name is written in Arabic but exists in Odoo in English (or vice versa), translate/match them intelligently. For example:\n"
        "     * User writes 'ابراهيم بيتي كاش' or 'بيتي كاش ابراهيم' -> Match it with Odoo Account code '102014' or Odoo partner 'Ibrahim Petty Cash' or similar from the list.\n"
        "     * User writes 'محمد شعبان' -> Match it with Odoo Partner 'Mohammed Ahmed Shaban' or similar from the list.\n"
        "   - In Column A (Account Code), you MUST fill the EXACT account code from the matched Odoo account (e.g. '102014', '501001', '101001'). Do not invent codes.\n"
        "   - In Column E (Partner), you MUST fill the EXACT name of the matched Odoo partner (e.g., 'Mohammed Ahmed Shaban' or 'Ibrahim Petty Cash') or the provided partner name if new.\n"
        "   - Ensure the Odoo matching is highly accurate and resolves minor spelling discrepancies.\n\n"
        "4. DOUBLE-ENTRY BOOKKEEPING & TRANSACTION BALANCING RULE:\n"
        "   - In double-entry bookkeeping (قيود يومية), every single transaction or amount must be recorded exactly twice: once as a Debit (مدين) entry and once as a Credit (دائن) entry.\n"
        "   - Whenever you format, clean, balance, review, or generate accounting entries, you MUST ensure that each transaction amount appears in two separate rows: one row where the amount is under the Debit column, and another row where the exact same amount is under the Credit column.\n"
        "   - If the user's spreadsheet contains single-sided entries (e.g. only debits or only credits), you MUST generate or duplicate those rows to provide their matching offset (e.g., offset against a bank/cash account, suspense account, or the correct matched Odoo account) so that the sheet is completely balanced (Total Debit equals Total Credit).\n"
        "   - Each transaction must have its offset, ensuring no single-sided entries remain in the final grid data.\n\n"
        "5. ODOO BANK RECONCILIATION RULES (BANK RULES) APPLICATION:\n"
        "   - You are provided with the active list of Odoo Bank Rules (Reconcile Models).\n"
        "   - When formatting bank entries or statements (قيد بنك / كشف حساب), check if the transaction details (البيان) matches any Odoo Bank Rule:\n"
        "     * If the rule's MatchLabel is 'contains' and its Param is present in the transaction details (case-insensitive), it is a match.\n"
        "     * If the rule's MatchLabel is 'match_regex' and its Param matches the transaction details as a regex pattern, it is a match.\n"
        "     * Examples: 'OUTGOING INSTANT PAYMENT' matches regex 'OUTGOING\\ INSTANT\\ PAYMENT' (rule 'Cash (copy)', maps to account code '105002'). 'INSTANT PAYMENT FEES' contains 'Fees' (rule 'Fees', maps to account code '400051').\n"
        "   - If a rule matches a transaction, you MUST map Column A (Account Code) to that rule's account code, and Column B (Description) to the rule's line label or transaction details. Map Column E (Partner) if the rule or text indicates a specific partner.\n"
        "   - If no rule matches, map it to a reasonable default account (e.g., Suspense Account or other relevant account).\n"
        "   - Every bank transaction must be split/represented as a double-entry (balanced Debit and Credit) where one row uses the matched rule account and the other row uses the bank account (e.g., code 101001 Riyadh Bank or active bank account).\n\n"
        "6. GENERAL GRID RULES:\n"
        "   - Keep cell grid dimensions consistent. The grid_data should be a rectangular array (all rows having the same number of columns).\n"
        "   - Output ONLY valid JSON. Do not include markdown wraps like ```json in your response, just the raw JSON object."
    )
 
    user_prompt = (
        f"User Request: \"{payload.prompt}\"\n\n"
        f"Active Sheet Details:\n"
        f"- Name: \"{active_sheet.name}\"\n"
        f"- ID: \"{active_sheet.id}\"\n"
        f"- Current Grid Data (Rows: {active_sheet.rowCount}, Cols: {active_sheet.colCount}):\n"
        f"{json.dumps(active_sheet.gridData, ensure_ascii=False)}\n\n"
        f"All Available Sheets in the Session:\n"
        f"{json.dumps([{'id': s.id, 'name': s.name} for s in payload.sheets], ensure_ascii=False)}\n\n"
        f"=== CONNECTED ODOO DATABASE CONTEXT ===\n"
        f"Odoo Accounts (Code, Name, Type):\n"
        f"{accounts_text[:20000]}\n\n"
        f"Odoo Partners (ID, Name):\n"
        f"{partners_text[:20000]}\n\n"
        f"Odoo Bank Rules (Reconcile Models):\n"
        f"{bank_rules_text[:15000]}\n"
    )

    result = llm_chat(system_prompt, user_prompt)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider is not configured. Please set ANTHROPIC_API_KEY or start Ollama locally.",
        )

    content = result
    # Clean markdown code blocks if present
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        response_obj = json.loads(content)
        return response_obj
    except Exception as e:
        logger.info(f"[Spreadsheet Agent Error] JSON parse failed: {e}")
        return {
            "message": f"عذراً، حدث خطأ أثناء الاتصال بمساعد التنسيق: {str(e)}",
            "grid_data": None
        }

