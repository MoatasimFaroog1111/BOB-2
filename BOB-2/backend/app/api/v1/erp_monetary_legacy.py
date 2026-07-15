"""Decimal-safe replacements for legacy ERP monetary endpoints.

The historical implementations in ``erp.py`` accepted binary floats and could
construct Odoo moves without exact fixed-point balance validation.  The API
router removes those two route objects before registration and exposes these
compatible, tenant-scoped replacements instead.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.money import (
    MoneyValidationError,
    NonNegativeMoney,
    PositiveMoney,
    canonical_money_lines,
    money_to_erp_float,
    money_to_str,
    validate_balanced_lines,
)
from app.db.database import get_db
from app.erp.factory import get_erp_provider
from app.models.core import AuditLog, ERPConnection, User
from app.security.dependencies import require_permission
from app.security.encryption import decrypt_value

router = APIRouter()

_REPLACED_PATHS = frozenset({"/propose-transaction", "/register-document"})


class LegacyMonetaryLine(BaseModel):
    account_id: int = Field(gt=0)
    account_name: str = ""
    account_code: str = ""
    debit: NonNegativeMoney = Decimal("0.00")
    credit: NonNegativeMoney = Decimal("0.00")
    name: str = Field(min_length=1, max_length=255)
    partner_id: int | None = Field(default=None, gt=0)
    partner_name: str = ""
    analytic_account_id: int | None = Field(default=None, gt=0)
    analytic_account_name: str = ""


class LegacyProposeTransactionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    document_class: str = Field(default="general", max_length=100)
    amount: PositiveMoney
    date: str
    partner_name: str = Field(default="", max_length=255)
    raw_text: str = Field(default="", max_length=4000)


class LegacyRegisterDocumentRequest(LegacyProposeTransactionRequest):
    partner_id: int | None = Field(default=None, gt=0)
    ref: str = Field(default="", max_length=255)
    lines: list[LegacyMonetaryLine] | None = Field(default=None, max_length=500)
    file_path: str | None = None


def replace_unsafe_legacy_routes(legacy_router: APIRouter) -> None:
    """Remove the float-based route objects before the router is included."""

    legacy_router.routes[:] = [
        route
        for route in legacy_router.routes
        if not (isinstance(route, APIRoute) and route.path in _REPLACED_PATHS)
    ]


def _current_user(db: Session, token: dict) -> User:
    user_id = token.get("user_id")
    user = db.query(User).filter(User.id == user_id).first() if user_id else None
    if user is None and token.get("sub"):
        user = db.query(User).filter(User.email == token["sub"]).first()
    if not user or not user.is_active or user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user is not associated with an active organization.",
        )
    return user


def _tenant_erp(db: Session, organization_id: int):
    connection = (
        db.query(ERPConnection)
        .filter(
            ERPConnection.organization_id == organization_id,
            ERPConnection.is_active.is_(True),
        )
        .order_by(ERPConnection.id.asc())
        .first()
    )
    if not connection or not connection.encrypted_secret_ref:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")
    try:
        credentials = json.loads(decrypt_value(connection.encrypted_secret_ref))
        username = str(credentials["username"])
        password = str(credentials["password"])
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="ERP credentials are unavailable from the centralized secret store.",
        ) from exc
    return connection, get_erp_provider(
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=username,
        password=password,
    ), username


def _company_id(erp: Any, username: str) -> int:
    users = erp.execute_kw(
        "res.users",
        "search_read",
        [[["login", "=", username]]],
        {"fields": ["company_id"], "limit": 1},
    )
    value = users[0].get("company_id") if users else None
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int) and value > 0:
        return value
    raise HTTPException(status_code=422, detail="Unable to resolve the ERP company.")


def _search_account(
    erp: Any,
    company_id: int,
    *,
    account_type: str | None = None,
    name_contains: str | None = None,
) -> dict[str, Any] | None:
    domain: list[Any] = [("company_ids", "in", [company_id])]
    if account_type:
        domain.append(("account_type", "=", account_type))
    if name_contains:
        domain.append(("name", "ilike", name_contains))
    rows = erp.execute_kw(
        "account.account",
        "search_read",
        [domain],
        {"fields": ["id", "name", "code", "company_ids", "deprecated"], "limit": 1},
    )
    return rows[0] if rows else None


def _search_journal(erp: Any, company_id: int, journal_type: str) -> dict[str, Any] | None:
    rows = erp.execute_kw(
        "account.journal",
        "search_read",
        [[("company_id", "=", company_id), ("type", "=", journal_type)]],
        {"fields": ["id", "name", "type", "default_account_id"], "limit": 1},
    )
    return rows[0] if rows else None


def _resolve_partner(erp: Any, company_id: int, partner_name: str) -> tuple[int | None, str]:
    name = partner_name.strip()
    if not name:
        return None, ""
    rows = erp.execute_kw(
        "res.partner",
        "search_read",
        [[("active", "=", True), ("company_id", "in", [False, company_id]), ("name", "ilike", name)]],
        {"fields": ["id", "name", "company_id"], "limit": 1},
    )
    if not rows:
        return None, name
    return int(rows[0]["id"]), str(rows[0].get("name") or name)


def _classification(payload: LegacyProposeTransactionRequest) -> str:
    blob = f"{payload.document_class} {payload.filename} {payload.raw_text}".lower()
    if any(term in blob for term in ("payroll", "salary", "مسير", "رواتب")):
        return "payroll"
    if any(term in blob for term in ("bank", "statement", "receipt", "كشف", "إيصال", "ايصال", "إشعار")):
        return "bank"
    if any(term in blob for term in ("invoice", "bill", "فاتورة")):
        return "invoice"
    return "general"


def _account_label(account: dict[str, Any]) -> str:
    return f"{account.get('code') or ''} {account.get('name') or ''}".strip()


def _build_proposal(
    erp: Any,
    company_id: int,
    payload: LegacyProposeTransactionRequest,
) -> dict[str, Any]:
    amount = payload.amount
    amount_text = money_to_str(amount)
    category = _classification(payload)
    expense = _search_account(erp, company_id, account_type="expense")
    payable = _search_account(erp, company_id, account_type="liability_payable")
    suspense = _search_account(erp, company_id, name_contains="suspense") or _search_account(
        erp, company_id, name_contains="clearing"
    )
    fallback = expense or _search_account(erp, company_id)
    if fallback is None:
        raise HTTPException(status_code=422, detail="No eligible ERP account was found.")
    expense = expense or fallback
    payable = payable or fallback
    suspense = suspense or fallback

    partner_id, partner_name = _resolve_partner(erp, company_id, payload.partner_name)
    debit_account = expense
    credit_account = payable if category in {"invoice", "payroll"} else suspense
    journal_type = "general"
    journal_name = "Miscellaneous Operations"
    if category == "bank":
        bank_journal = _search_journal(erp, company_id, "bank")
        default_account = bank_journal.get("default_account_id") if bank_journal else None
        if isinstance(default_account, (list, tuple)) and default_account:
            credit_account = {
                "id": int(default_account[0]),
                "name": str(default_account[1] if len(default_account) > 1 else "Bank"),
                "code": "",
            }
        journal_type = "bank"
        journal_name = str(bank_journal.get("name") or "Bank") if bank_journal else "Bank"

    debit_name = {
        "invoice": "Invoice expense",
        "payroll": "Payroll expense",
        "bank": "Bank transaction",
        "general": "General document",
    }[category]
    credit_name = {
        "invoice": "Supplier payable",
        "payroll": "Payroll payable",
        "bank": "Bank clearing",
        "general": "Document offset",
    }[category]
    lines = canonical_money_lines(
        [
            {
                "account_id": int(debit_account["id"]),
                "account_name": _account_label(debit_account),
                "account_code": str(debit_account.get("code") or ""),
                "debit": amount_text,
                "credit": "0.00",
                "name": f"{debit_name}: {payload.filename}"[:255],
                "partner_id": partner_id,
                "partner_name": partner_name,
            },
            {
                "account_id": int(credit_account["id"]),
                "account_name": _account_label(credit_account),
                "account_code": str(credit_account.get("code") or ""),
                "debit": "0.00",
                "credit": amount_text,
                "name": f"{credit_name}: {payload.filename}"[:255],
                "partner_id": partner_id,
                "partner_name": partner_name,
            },
        ]
    )
    validate_balanced_lines(lines)
    return {
        "status": "success",
        "document_class": category,
        "amount": amount_text,
        "money_scale": 2,
        "suggested_partner_id": partner_id,
        "suggested_partner_name": partner_name,
        "journal_type": journal_type,
        "journal_name": journal_name,
        "rule_matched": None,
        "lines": lines,
    }


def _safe_date(raw: str) -> str:
    value = raw.strip()
    if not value:
        return date.today().isoformat()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Accounting date must use YYYY-MM-DD.") from exc


def _verify_accounts(erp: Any, company_id: int, account_ids: list[int]) -> None:
    rows = erp.execute_kw(
        "account.account",
        "search_read",
        [[("id", "in", sorted(set(account_ids))), ("company_ids", "in", [company_id])]],
        {"fields": ["id", "deprecated"], "limit": len(set(account_ids))},
    )
    found = {int(row["id"]) for row in rows if not row.get("deprecated")}
    missing = sorted(set(account_ids) - found)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Account IDs are missing, deprecated, or outside the ERP company: {missing}",
        )


def _content_key(
    organization_id: int,
    accounting_date: str,
    reference: str,
    lines: list[dict[str, Any]],
) -> str:
    canonical = json.dumps(
        {
            "organization_id": organization_id,
            "date": accounting_date,
            "reference": reference,
            "lines": lines,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.post("/propose-transaction")
def propose_transaction_fixed_point(
    payload: LegacyProposeTransactionRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("create_entries")),
):
    user = _current_user(db, token)
    _connection, erp, username = _tenant_erp(db, user.organization_id)
    proposal = _build_proposal(erp, _company_id(erp, username), payload)
    proposal["organization_id"] = user.organization_id
    return proposal


@router.post("/register-document")
def register_document_fixed_point(
    payload: LegacyRegisterDocumentRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(require_permission("post_odoo_entries")),
):
    user = _current_user(db, token)
    connection, erp, username = _tenant_erp(db, user.organization_id)
    company_id = _company_id(erp, username)
    if payload.file_path:
        raise HTTPException(
            status_code=422,
            detail="Server-side file paths are no longer accepted. Attach the document through the authenticated attachment endpoint.",
        )

    proposal = _build_proposal(erp, company_id, payload)
    raw_lines = [line.model_dump() for line in payload.lines] if payload.lines else proposal["lines"]
    try:
        total_debit, total_credit = validate_balanced_lines(raw_lines)
        lines = canonical_money_lines(raw_lines)
    except MoneyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if total_debit != payload.amount:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Document amount {money_to_str(payload.amount)} does not equal "
                f"the balanced journal total {money_to_str(total_debit)}."
            ),
        )

    account_ids = [int(line["account_id"]) for line in lines]
    _verify_accounts(erp, company_id, account_ids)
    accounting_date = _safe_date(payload.date)
    base_ref = (payload.ref or f"Doc {payload.filename}").strip()[:180]
    key = _content_key(user.organization_id, accounting_date, base_ref, lines)
    full_ref = f"{base_ref} | BOB-MONEY:{key[:24]}"
    existing = erp.execute_kw(
        "account.move",
        "search_read",
        [[("company_id", "=", company_id), ("ref", "=", full_ref)]],
        {"fields": ["id", "name", "state"], "limit": 1},
    )
    if existing:
        move = existing[0]
        return {
            "status": "duplicate_prevented",
            "message": "Duplicate document registration was prevented.",
            "move_id": int(move["id"]),
            "move_name": str(move.get("name") or f"MOVE/{move['id']}"),
            "odoo_url": f"{connection.base_url.rstrip('/')}/web#id={move['id']}&model=account.move&view_type=form",
            "amount": money_to_str(total_debit),
            "money_scale": 2,
            "idempotency_key": key,
        }

    journal_type = str(proposal.get("journal_type") or "general")
    journal = _search_journal(erp, company_id, journal_type) or _search_journal(
        erp, company_id, "general"
    )
    move_values: dict[str, Any] = {
        "move_type": "entry",
        "company_id": company_id,
        "date": accounting_date,
        "ref": full_ref,
        "line_ids": [
            (
                0,
                0,
                {
                    "account_id": int(line["account_id"]),
                    "name": str(line.get("name") or payload.filename)[:255],
                    "debit": money_to_erp_float(line["debit"]),
                    "credit": money_to_erp_float(line["credit"]),
                    "partner_id": line.get("partner_id") or payload.partner_id or False,
                },
            )
            for line in lines
        ],
    }
    if journal:
        move_values["journal_id"] = int(journal["id"])
    move_id = int(erp.execute_kw("account.move", "create", [move_values]))
    move_name = f"MOVE/{move_id}"
    try:
        created = erp.execute_kw("account.move", "read", [[move_id]], {"fields": ["name"]})
        if created and created[0].get("name"):
            move_name = str(created[0]["name"])
    except Exception:
        pass

    db.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action="erp_document_registered_fixed_point",
            entity_type="account.move",
            entity_id=str(move_id),
            details={
                "reference_hash": hashlib.sha256(full_ref.encode("utf-8")).hexdigest(),
                "amount": money_to_str(total_debit),
                "total_debit": money_to_str(total_debit),
                "total_credit": money_to_str(total_credit),
                "money_scale": 2,
                "idempotency_key": key,
            },
        )
    )
    db.commit()
    return {
        "status": "success",
        "message": "Transaction created successfully in Odoo.",
        "move_id": move_id,
        "move_name": move_name,
        "odoo_url": f"{connection.base_url.rstrip('/')}/web#id={move_id}&model=account.move&view_type=form",
        "partner_name": payload.partner_name,
        "journal_name": str(journal.get("name") or "") if journal else "",
        "account_id": account_ids[0],
        "attachment_id": None,
        "amount": money_to_str(total_debit),
        "money_scale": 2,
        "idempotency_key": key,
    }
