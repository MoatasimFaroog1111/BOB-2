import hashlib
import json
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import AuditLog, ERPConnection, User
from app.security.dependencies import require_permission
from app.security.encryption import decrypt_value

router = APIRouter()


class BankPostingLineV2(BaseModel):
    account_id: int
    account_name: str = ""
    account_code: str = ""
    debit: float = 0.0
    credit: float = 0.0
    name: str
    partner_id: Optional[int] = None
    partner_name: str = ""
    analytic_account_id: Optional[int] = None
    analytic_account_name: str = ""


class BankPostingRequestV2(BaseModel):
    company_id: Optional[int] = None
    journal_type: str = "bank"
    journal_id: Optional[int] = None
    date: str = ""
    ref: str = ""
    filename: str = "bank_statement_reconciliation"
    amount: float = 0.0
    partner_name: str = ""
    statement_ref: str = ""
    row_number: Optional[int] = None
    idempotency_key: str = ""
    approval_status: str = "approved"
    attachment_name: str = ""
    attachment_mimetype: str = ""
    attachment_content_base64: str = ""
    lines: List[BankPostingLineV2]


def safe_date(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Invalid or missing accounting date. Row requires manual review.")
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid accounting date format. Expected YYYY-MM-DD.")
    return raw


def normalized_journal_type(value: str) -> str:
    raw = (value or "bank").strip().lower()
    aliases = {
        "bank": "bank",
        "cash": "bank",
        "misc": "general",
        "miscellaneous": "general",
        "miscellaneous_operations": "general",
        "general": "general",
        "entry": "general",
        "vendor_bill": "purchase",
        "vendor bills": "purchase",
        "bill": "purchase",
        "purchase": "purchase",
        "customer_invoice": "sale",
        "customer invoices": "sale",
        "invoice": "sale",
        "sale": "sale",
        "sales": "sale",
    }
    return aliases.get(raw, "bank")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def first_line_description(payload: BankPostingRequestV2) -> str:
    for line in payload.lines:
        if line.name:
            return line.name
    return payload.ref or payload.filename or "bank-reconciliation-entry"


def build_idempotency_key(organization_id: int, company_id: int, payload: BankPostingRequestV2) -> str:
    if payload.idempotency_key.strip():
        return payload.idempotency_key.strip()
    description_hash = hashlib.sha256(normalize_text(first_line_description(payload)).encode("utf-8")).hexdigest()[:24]
    raw = "|".join(
        [
            str(organization_id),
            str(company_id),
            safe_date(payload.date),
            f"{float(payload.amount or 0.0):.2f}",
            normalize_text(payload.statement_ref or payload.ref),
            str(payload.row_number or ""),
            description_hash,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def add_analytic(vals: dict, analytic_account_id: Optional[int], supported_fields: set[str]) -> dict:
    if not analytic_account_id:
        return vals
    analytic_id = int(analytic_account_id)
    if "analytic_distribution" in supported_fields:
        vals["analytic_distribution"] = {str(analytic_id): 100.0}
        return vals
    if "analytic_account_id" in supported_fields:
        vals["analytic_account_id"] = analytic_id
        return vals
    raise ValueError("Analytic field is not available in this Odoo version. Row requires manual review.")


def normalize_attachment_content(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "," in raw and raw.lower().startswith("data:"):
        return raw.split(",", 1)[1]
    return raw


def get_authenticated_user(db_session: Session, token_payload: dict) -> User:
    email = token_payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token subject.")
    user = db_session.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")
    if user.organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not assigned to an organization.")
    return user


def audit(
    db_session: Session,
    *,
    user: User,
    action: str,
    result: str,
    request: Request,
    entity_id: str | None = None,
    details: dict | None = None,
) -> None:
    db_session.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action=action,
            entity_type="bank_reconciliation_posting",
            entity_id=entity_id,
            ip_address=request.client.host if request.client else None,
            details={
                "result": result,
                "user_agent": request.headers.get("user-agent"),
                **(details or {}),
            },
        )
    )
    db_session.commit()


def attach_document_to_move(erp, move_id: int, payload: BankPostingRequestV2) -> tuple[Optional[int], str]:
    content = normalize_attachment_content(payload.attachment_content_base64)
    if not content:
        return None, ""
    name = payload.attachment_name or f"{payload.ref or 'bank-reconciliation-entry'}.pdf"
    vals = {
        "name": name,
        "res_model": "account.move",
        "res_id": int(move_id),
        "type": "binary",
        "datas": content,
    }
    if payload.attachment_mimetype:
        vals["mimetype"] = payload.attachment_mimetype
    attachment_id = erp.execute_kw("ir.attachment", "create", [vals])
    return int(attachment_id), name


def read_company_id_from_odoo_user(erp, username: str) -> int:
    users = erp.execute_kw("res.users", "search_read", [[["login", "=", username]]], {"fields": ["company_id"], "limit": 1})
    company_value = users[0]["company_id"] if users and users[0].get("company_id") else None
    if not company_value:
        raise ValueError("Unable to resolve Odoo company for the current ERP user.")
    return int(company_value[0] if isinstance(company_value, list) else company_value)


def get_move_line_analytic_fields(erp) -> set[str]:
    try:
        fields = erp.execute_kw("account.move.line", "fields_get", [], {"attributes": ["type"]})
    except Exception as exc:
        raise ValueError(f"Unable to inspect Odoo analytic fields: {exc}")
    return {name for name in ("analytic_distribution", "analytic_account_id") if name in fields}


def verify_accounts_belong_to_company(erp, account_ids: list[int], company_id: int) -> None:
    if not account_ids:
        raise ValueError("No accounts supplied for journal entry lines.")
    accounts = erp.execute_kw(
        "account.account",
        "search_read",
        [[["id", "in", account_ids]]],
        {"fields": ["id", "code", "name", "company_id", "deprecated"]},
    )
    found_ids = {int(account["id"]) for account in accounts}
    missing = sorted(set(account_ids) - found_ids)
    if missing:
        raise ValueError(f"Account(s) not found in Odoo: {missing}")
    for account in accounts:
        company_value = account.get("company_id")
        account_company_id = company_value[0] if isinstance(company_value, list) and company_value else company_value
        if account_company_id and int(account_company_id) != int(company_id):
            raise ValueError(f"Account {account.get('code') or account.get('id')} belongs to another company.")
        if account.get("deprecated"):
            raise ValueError(f"Account {account.get('code') or account.get('id')} is deprecated and cannot be posted to.")


def verify_partners_belong_to_company(erp, partner_ids: list[int], company_id: int) -> None:
    if not partner_ids:
        return
    partners = erp.execute_kw(
        "res.partner",
        "search_read",
        [[["id", "in", partner_ids]]],
        {"fields": ["id", "name", "company_id"]},
    )
    found_ids = {int(partner["id"]) for partner in partners}
    missing = sorted(set(partner_ids) - found_ids)
    if missing:
        raise ValueError(f"Partner(s) not found in Odoo: {missing}")
    for partner in partners:
        company_value = partner.get("company_id")
        partner_company_id = company_value[0] if isinstance(company_value, list) and company_value else company_value
        if partner_company_id and int(partner_company_id) != int(company_id):
            raise ValueError(f"Partner {partner.get('name') or partner.get('id')} belongs to another company.")


def find_journal(erp, company_id: int, payload: BankPostingRequestV2) -> tuple[int, str, str]:
    journal_type = normalized_journal_type(payload.journal_type)
    if payload.journal_id:
        journals = erp.execute_kw(
            "account.journal",
            "search_read",
            [[["id", "=", int(payload.journal_id)], ["company_id", "=", int(company_id)]]],
            {"fields": ["id", "name", "type"], "limit": 1},
        )
        if not journals:
            raise ValueError("Selected journal does not belong to the selected company.")
        return int(journals[0]["id"]), journals[0].get("name") or "", journals[0].get("type") or journal_type

    for candidate in [journal_type, "general"]:
        journals = erp.execute_kw(
            "account.journal",
            "search_read",
            [[["type", "=", candidate], ["company_id", "=", int(company_id)]]],
            {"fields": ["id", "name", "type"], "limit": 1},
        )
        if journals:
            return int(journals[0]["id"]), journals[0].get("name") or "", journals[0].get("type") or candidate
    raise ValueError("No suitable Odoo journal found for the selected company.")


@router.post("/register-bank-reconciliation-entry-v2")
def register_bank_reconciliation_entry_v2(
    payload: BankPostingRequestV2,
    request: Request,
    db_session: Session = Depends(get_db),
    token_payload: dict = Depends(require_permission("post_odoo_entries")),
):
    user = get_authenticated_user(db_session, token_payload)
    if not payload.lines or len(payload.lines) < 2:
        raise HTTPException(status_code=400, detail="At least two journal lines are required.")
    if (payload.approval_status or "").strip().lower() != "approved":
        raise HTTPException(status_code=403, detail="Entry must be approved before posting to Odoo.")

    total_debit = round(sum(float(line.debit or 0.0) for line in payload.lines), 2)
    total_credit = round(sum(float(line.credit or 0.0) for line in payload.lines), 2)
    if total_debit != total_credit:
        raise HTTPException(status_code=400, detail=f"Journal entry is not balanced: debit={total_debit}, credit={total_credit}")

    try:
        conn = (
            db_session.query(ERPConnection)
            .filter(ERPConnection.organization_id == int(user.organization_id), ERPConnection.is_active.is_(True))
            .first()
        )
        if not conn:
            raise HTTPException(status_code=404, detail="No active ERP connection found for the authenticated organization.")

        try:
            secret = json.loads(decrypt_value(conn.encrypted_secret_ref))
            username = secret.get("username")
            password = secret.get("password")
            if not username or not password:
                raise ValueError("ERP username or password is missing.")
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

        erp = get_erp_provider(provider=conn.provider, url=conn.base_url, db=conn.database_name or "", username=username, password=password)
        company_id = int(payload.company_id or read_company_id_from_odoo_user(erp, username))
        posting_date = safe_date(payload.date)
        idempotency_key = build_idempotency_key(int(user.organization_id), company_id, payload)
        ref_base = payload.ref or f"Bank statement reconciliation {payload.filename}"
        full_ref = f"{ref_base} | BOB-IDEMP:{idempotency_key}"

        existing_moves = erp.execute_kw(
            "account.move",
            "search_read",
            [[["ref", "=", full_ref], ["company_id", "=", company_id]]],
            {"fields": ["id", "name", "state"], "limit": 1},
        )
        if existing_moves:
            move = existing_moves[0]
            audit(
                db_session,
                user=user,
                action="odoo_duplicate_prevented",
                result="duplicate_prevented",
                request=request,
                entity_id=str(move.get("id")),
                details={"idempotency_key": idempotency_key, "ref": full_ref},
            )
            return {
                "status": "duplicate_prevented",
                "message": "Duplicate posting prevented. Existing Odoo journal entry was reused.",
                "move_id": move.get("id"),
                "move_name": move.get("name") or f"JE/{move.get('id')}",
                "idempotency_key": idempotency_key,
                "company_id": company_id,
            }

        journal_id, journal_name, journal_type = find_journal(erp, company_id, payload)
        account_ids = sorted({int(line.account_id) for line in payload.lines})
        partner_ids = sorted({int(line.partner_id) for line in payload.lines if line.partner_id})
        verify_accounts_belong_to_company(erp, account_ids, company_id)
        verify_partners_belong_to_company(erp, partner_ids, company_id)
        analytic_fields = get_move_line_analytic_fields(erp)

        line_ids = []
        for line in payload.lines:
            vals = {
                "account_id": int(line.account_id),
                "name": line.name or payload.ref or "Bank reconciliation entry",
                "debit": float(line.debit or 0.0),
                "credit": float(line.credit or 0.0),
            }
            if line.partner_id:
                vals["partner_id"] = int(line.partner_id)
            line_ids.append((0, 0, add_analytic(vals, line.analytic_account_id, analytic_fields)))

        move_vals = {
            "move_type": "entry",
            "date": posting_date,
            "ref": full_ref,
            "line_ids": line_ids,
            "company_id": company_id,
            "journal_id": journal_id,
        }

        move_id = erp.execute_kw("account.move", "create", [move_vals])
        move_name = f"JE/{move_id}"
        try:
            created = erp.execute_kw("account.move", "read", [[move_id]], {"fields": ["name"]})
            if created and created[0].get("name"):
                move_name = created[0]["name"]
        except Exception:
            pass

        attachment_id = None
        attachment_name = ""
        attachment_error = ""
        try:
            attachment_id, attachment_name = attach_document_to_move(erp, int(move_id), payload)
        except Exception as attachment_exc:
            attachment_error = str(attachment_exc)

        audit(
            db_session,
            user=user,
            action="odoo_bank_reconciliation_entry_created",
            result="posted_with_attachment_error" if attachment_error else "success",
            request=request,
            entity_id=str(move_id),
            details={
                "idempotency_key": idempotency_key,
                "company_id": company_id,
                "journal_id": journal_id,
                "move_name": move_name,
                "attachment_id": attachment_id,
                "attachment_error": attachment_error,
            },
        )

        base_url = conn.base_url.rstrip("/")
        return {
            "status": "posted_with_attachment_error" if attachment_error else "success",
            "message": "Bank reconciliation entry created successfully in Odoo" if not attachment_error else "Entry created in Odoo, but attachment upload failed.",
            "move_id": move_id,
            "move_name": move_name,
            "odoo_url": f"{base_url}/web#id={move_id}&model=account.move&view_type=form",
            "attachment_id": attachment_id,
            "attachment_name": attachment_name,
            "attachment_error": attachment_error,
            "idempotency_key": idempotency_key,
            "company_id": company_id,
            "journal_id": journal_id,
            "journal_name": journal_name,
            "journal_type": journal_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        audit(
            db_session,
            user=user,
            action="odoo_bank_reconciliation_entry_failed",
            result="failed",
            request=request,
            details={"error": str(e), "ref": payload.ref},
        )
        raise HTTPException(status_code=400, detail=f"Failed to create bank reconciliation entry in Odoo: {str(e)}")
