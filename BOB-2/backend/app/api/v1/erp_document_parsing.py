"""Manual document parsing and attachment-detection HTTP component."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.erp.partner_matching import closest_partner as _closest_partner_by_name
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value
from app.security.tenant_scope import current_organization_id
from app.services.llm_service import chat as llm_chat

logger = logging.getLogger(__name__)
router = APIRouter()


class ParseManualTextRequest(BaseModel):
    text: str
    company_id: Optional[int] = 1


@router.post("/parse-manual-text")
def parse_manual_text(payload: ParseManualTextRequest, db_session: Session = Depends(get_db)):
    # Fetch dynamic Odoo accounts and partners if connection is active
    odoo_accounts = []
    odoo_partners = []
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
            odoo_connected = True
            logger.info(f"[Parse Manual Text] Loaded {len(odoo_partners)} partners and {len(odoo_accounts)} accounts from Odoo.")
    except Exception as e:
        logger.info(f"[Parse Manual Text] Failed to fetch Odoo context: {e}")

    # Format Odoo context for LLM
    partners_text = ""
    accounts_text = ""
    if odoo_connected:
        partners_text = "\n".join([f"- ID: {p['id']}, Name: {p['name']}" for p in odoo_partners if p.get('name')])
        accounts_text = "\n".join([f"- Code: {a['code']}, Name: {a['name']}, Type: {a['account_type']}" for a in odoo_accounts])
    else:
        partners_text = "No active Odoo connection or could not fetch partners."
        accounts_text = "No active Odoo connection or could not fetch accounts."

    system_prompt = (
        "You are an exceptionally intelligent accounting parsing agent.\n"
        "Your task is to take a raw text input written or pasted by the user and extract journal entry details from it.\n"
        "The input text could be a pasted table (tab-separated or comma-separated rows) or natural language description of an accounting transaction.\n"
        "You must extract the following fields:\n"
        "- Transaction Date: (YYYY-MM-DD format, fallback to today's date if not specified)\n"
        "- Transaction Reference / Description: (string)\n"
        "- Journal Name / Class: (general_journal, bank, invoice, etc.)\n"
        "- Lines: A list of journal entry lines, where each line contains:\n"
        "  * account_code: (string, the account code or code pattern referenced in the text)\n"
        "  * name: (string, the line description or account description)\n"
        "  * debit: (float, 0.0 if not specified)\n"
        "  * credit: (float, 0.0 if not specified)\n"
        "  * partner_name: (string, the partner name if specified, empty string otherwise)\n\n"
        "You must return ONLY a valid JSON object with the following schema:\n"
        "{\n"
        "  \"date\": \"YYYY-MM-DD\",\n"
        "  \"ref\": \"Description\",\n"
        "  \"journal\": \"general_journal\" | \"bank\" | \"invoice\",\n"
        "  \"lines\": [\n"
        "    {\n"
        "      \"account_code\": \"code\",\n"
        "      \"name\": \"line explanation\",\n"
        "      \"debit\": 100.0,\n"
        "      \"credit\": 0.0,\n"
        "      \"partner_name\": \"partner name\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "CRITICAL RULES:\n"
        "1. Direct Mapping: Try to match and assign account codes based on the available Odoo Accounts and Partner lists provided in the prompt.\n"
        "2. Typo Tolerance: Correct any spelling mistakes or translation discrepancies.\n"
        "3. Value Added Tax (VAT) Splitting:\n"
        "   - Analyze the raw text for VAT or tax details (e.g. 'VAT AMOUNT 0.15' on a fee of '1.00', or '1.15 inclusive of 0.15 VAT').\n"
        "   - For any transaction that contains a VAT component, you MUST split the debit side into two lines:\n"
        "     * Base fee/expense debit: Debit the base fee amount (e.g., 1.00) to the respective bank charges/expense account (e.g., code 400051).\n"
        "     * VAT debit: Debit the VAT amount (e.g., 0.15) to the VAT input tax account (code 104041).\n"
        "4. Individual Credit Offsets (No Grouping):\n"
        "   - Do NOT group the credit/offset side into a single summary line.\n"
        "   - Every debit transaction (base + VAT) must have its own corresponding credit line to the bank account (e.g., Riyadh Bank 101001) matching its exact transaction total.\n"
        "   - If there are multiple separate transactions, generate separate credit offsets for each one so they can be reconciled line-by-line in Odoo.\n"
        "5. Output format: Return ONLY the raw JSON object. Do not include markdown code block syntax (like ```json)."
    )

    user_prompt = (
        f"User Input Text:\n\"\"\"\n{payload.text}\n\"\"\"\n\n"
        f"=== CONNECTED ODOO DATABASE CONTEXT ===\n"
        f"Odoo Accounts (Code, Name, Type):\n"
        f"{accounts_text[:30000]}\n\n"
        f"Odoo Partners (ID, Name):\n"
        f"{partners_text[:30000]}\n"
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
        parsed_data = json.loads(content)

        # Resolve accounts and partners context
        resolved_lines = []
        for line in parsed_data.get("lines", []):
            parsed_code = str(line.get("account_code", "")).strip()
            parsed_debit = float(line.get("debit") or 0.0)
            parsed_credit = float(line.get("credit") or 0.0)
            parsed_name = str(line.get("name", "")).strip()
            parsed_partner = str(line.get("partner_name", "")).strip()

            # Match Account
            matched_acc = None
            if parsed_code and odoo_accounts:
                matched_acc = next((a for a in odoo_accounts if a["code"] == parsed_code), None)
                if not matched_acc:
                    # Fuzzy match by code contains or name contains
                    matched_acc = next((a for a in odoo_accounts if parsed_code.lower() in a["code"].lower() or (a["name"] and isinstance(a["name"], str) and parsed_code.lower() in a["name"].lower())), None)

            # Match Partner
            matched_partner_id = None
            matched_partner_name = parsed_partner
            if parsed_partner and odoo_partners:
                matched_partner_id, matched_partner_name, _ = _closest_partner_by_name(
                    odoo_partners, parsed_partner
                )

            resolved_lines.append({
                "account_id": matched_acc["id"] if matched_acc else 0,
                "account_name": f"{matched_acc['code']} {matched_acc['name']}" if matched_acc else (f"{parsed_code} (غير معرف)" if parsed_code else "حساب غير محدد"),
                "account_code": matched_acc["code"] if matched_acc else parsed_code,
                "debit": parsed_debit,
                "credit": parsed_credit,
                "name": parsed_name or "قيد يدوي",
                "partner_id": matched_partner_id,
                "partner_name": matched_partner_name
            })

        return {
            "status": "success",
            "date": parsed_data.get("date") or "",
            "ref": parsed_data.get("ref") or "",
            "journal": parsed_data.get("journal") or "general_journal",
            "lines": resolved_lines
        }
    except Exception as e:
        logger.info(f"[Parse Manual Text Error] JSON parse failed: {e}")
        return {
            "status": "error",
            "message": f"عذراً، حدث خطأ أثناء تحليل النص المدخل: {str(e)}",
            "lines": []
        }


class DetectAttachmentsRequest(BaseModel):
    company_id: Optional[int] = 1
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    account_id: Optional[int] = None


@router.post("/detect-attachments")
def detect_attachments(payload: DetectAttachmentsRequest, db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == current_organization_id(required=True),
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        # Resolve Company ID
        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1}
        )
        user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        # Build domain
        domain = []
        if user_company_id:
            domain.append(["company_id", "=", user_company_id])

        if payload.account_id:
            # If account is filtered, find move lines for this account first
            line_domain = [["account_id", "=", payload.account_id]]
            if user_company_id:
                line_domain.append(["company_id", "=", user_company_id])
            if payload.date_from:
                line_domain.append(["date", ">=", payload.date_from])
            if payload.date_to:
                line_domain.append(["date", "<=", payload.date_to])

            lines = erp.execute_kw(
                "account.move.line",
                "search_read",
                [line_domain],
                {
                    "fields": ["move_id"],
                    "limit": 1000,
                }
            )

            move_ids = []
            for line in lines:
                m_val = line.get("move_id")
                if m_val and isinstance(m_val, list):
                    move_ids.append(m_val[0])
                elif isinstance(m_val, int):
                    move_ids.append(m_val)

            move_ids = list(set(move_ids))

            if not move_ids:
                return {
                    "status": "success",
                    "attached": [],
                    "not_attached": [],
                    "summary": {"attached_count": 0, "not_attached_count": 0, "total_count": 0}
                }

            domain.append(["id", "in", move_ids])
        else:
            # If no account filter, apply date filters directly on account.move
            if payload.date_from:
                domain.append(["date", ">=", payload.date_from])
            if payload.date_to:
                domain.append(["date", "<=", payload.date_to])

        # Query the moves
        moves = erp.execute_kw(
            "account.move",
            "search_read",
            [domain],
            {
                "fields": ["id", "name", "ref", "date", "amount_total", "partner_id", "journal_id"],
                "order": "date desc, name desc",
                "limit": 300,
            }
        )

        if not moves:
            return {
                "status": "success",
                "attached": [],
                "not_attached": [],
                "summary": {"attached_count": 0, "not_attached_count": 0, "total_count": 0}
            }

        move_ids = [m["id"] for m in moves]

        # Fetch detailed lines for all these moves
        move_lines_data = []
        if move_ids:
            try:
                move_lines_data = erp.execute_kw(
                    "account.move.line",
                    "search_read",
                    [[["move_id", "in", move_ids]]],
                    {"fields": ["id", "move_id", "account_id", "name", "debit", "credit"]}
                )
            except Exception as le:
                logger.info(f"[Detect Attachments] Failed to fetch move lines: {le}")

        # Group lines by move_id
        lines_by_move = {}
        for line in move_lines_data:
            m_id = line["move_id"][0] if isinstance(line["move_id"], list) and len(line["move_id"]) > 0 else (line["move_id"] if isinstance(line["move_id"], int) else None)
            if not m_id:
                continue
            lines_by_move.setdefault(m_id, []).append({
                "id": line["id"],
                "account_code": line["account_id"][1].split(" ")[0] if isinstance(line["account_id"], list) and len(line["account_id"]) > 1 else "",
                "account_name": line["account_id"][1] if isinstance(line["account_id"], list) and len(line["account_id"]) > 1 else "",
                "name": line.get("name") or "",
                "debit": line.get("debit") or 0.0,
                "credit": line.get("credit") or 0.0,
            })

        # Check attachments in ir.attachment
        attachments = erp.execute_kw(
            "ir.attachment",
            "search_read",
            [[["res_model", "=", "account.move"], ["res_id", "in", move_ids]]],
            {
                "fields": ["id", "res_id", "name"],
            }
        )

        attached_move_ids = set()
        move_attachments = {}
        for att in attachments:
            res_id = att["res_id"]
            attached_move_ids.add(res_id)
            move_attachments.setdefault(res_id, []).append({
                "id": att["id"],
                "name": att["name"]
            })

        attached_list = []
        not_attached_list = []

        for m in moves:
            mid = m["id"]

            # Format partner
            partner_name = ""
            p_val = m.get("partner_id")
            if p_val and isinstance(p_val, list) and len(p_val) > 1:
                partner_name = p_val[1]
            elif isinstance(p_val, str):
                partner_name = p_val

            # Format journal
            journal_name = ""
            j_val = m.get("journal_id")
            if j_val and isinstance(j_val, list) and len(j_val) > 1:
                journal_name = j_val[1]

            move_data = {
                "id": mid,
                "name": m.get("name") or "",
                "ref": m.get("ref") or "",
                "date": m.get("date") or "",
                "amount_total": m.get("amount_total") or 0.0,
                "partner_name": partner_name,
                "journal_name": journal_name,
                "attachments": move_attachments.get(mid, []),
                "lines": lines_by_move.get(mid, []),
            }

            if mid in attached_move_ids:
                attached_list.append(move_data)
            else:
                not_attached_list.append(move_data)

        return {
            "status": "success",
            "attached": attached_list,
            "not_attached": not_attached_list,
            "summary": {
                "attached_count": len(attached_list),
                "not_attached_count": len(not_attached_list),
                "total_count": len(moves)
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Odoo query failed: {str(e)}")
