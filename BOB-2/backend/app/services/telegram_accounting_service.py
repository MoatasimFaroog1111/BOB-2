"""Independent accounting service for Telegram-originated operations.

This module deliberately has no dependency on FastAPI route modules. Every operation
requires an explicit actor context, organization, source, current permission check,
content hash, expiring one-time token, and an atomic state transition before Odoo is
called.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.erp.factory import get_erp_provider
from app.models.core import (
    ERPConnection,
    Organization,
    TelegramApprovalOperation,
    TelegramAuthorization,
    User,
)
from app.security.encryption import decrypt_value
from app.security.roles import role_has_permission
from app.services.telegram_security import TelegramSecurityContext, record_telegram_event


class TelegramApprovalDenied(Exception):
    """Safe denial returned for invalid, expired, replayed, or unauthorized approvals."""

    def __init__(self, reason: str, public_message: str = "تعذر اعتماد العملية بصورة آمنة."):
        super().__init__(reason)
        self.reason = reason
        self.public_message = public_message


@dataclass(frozen=True, slots=True)
class ApprovalCreationResult:
    operation_id: int
    approval_token: str
    expires_at: datetime
    proposal: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ApprovalPostingResult:
    operation_id: int
    move_id: int
    move_name: str
    attachment_id: int | None
    odoo_url: str


def _utcnow() -> datetime:
    return datetime.utcnow()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    return _sha256_text(token)


def _file_sha256(file_path: str | None) -> str | None:
    if not file_path:
        return None
    path = Path(file_path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_content(
    *,
    organization_id: int,
    authorization_id: int,
    telegram_user_id: int,
    telegram_chat_id: int,
    system_user_id: int,
    source: str,
    payload: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "organization_id": organization_id,
            "authorization_id": authorization_id,
            "telegram_user_id": telegram_user_id,
            "telegram_chat_id": telegram_chat_id,
            "system_user_id": system_user_id,
            "source": source,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _content_hash_for_values(**kwargs: Any) -> str:
    return _sha256_text(_canonical_content(**kwargs))


def _content_hash_for_row(row: TelegramApprovalOperation) -> str:
    return _content_hash_for_values(
        organization_id=row.organization_id,
        authorization_id=row.authorization_id,
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        system_user_id=row.system_user_id,
        source=row.source,
        payload=row.payload,
    )


def _safe_amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TelegramApprovalDenied("invalid_amount", "المبلغ المستخرج غير صالح.") from exc
    if not amount.is_finite() or amount <= 0:
        raise TelegramApprovalDenied("invalid_amount", "المبلغ المستخرج غير صالح.")
    if amount > Decimal("999999999999999.9999"):
        raise TelegramApprovalDenied("amount_limit_exceeded", "المبلغ يتجاوز الحد المسموح.")
    return amount.quantize(Decimal("0.0001"))


def _validate_actor(
    db: Session,
    context: TelegramSecurityContext,
    required_permissions: Iterable[str],
) -> tuple[Organization, User, TelegramAuthorization]:
    organization = db.query(Organization).filter(Organization.id == context.organization_id).first()
    user = db.query(User).filter(User.id == context.system_user_id).first()
    authorization = (
        db.query(TelegramAuthorization)
        .filter(TelegramAuthorization.id == context.authorization_id)
        .first()
    )
    valid = (
        organization is not None
        and organization.is_active
        and user is not None
        and user.is_active
        and user.organization_id == context.organization_id
        and authorization is not None
        and authorization.is_active
        and authorization.organization_id == context.organization_id
        and authorization.system_user_id == context.system_user_id
        and authorization.telegram_user_id == context.telegram_user_id
        and authorization.telegram_chat_id == context.telegram_chat_id
    )
    if not valid:
        raise TelegramApprovalDenied(
            "actor_binding_invalid",
            "تم إلغاء أو تغيير صلاحية حساب Telegram المرتبط.",
        )
    missing = [permission for permission in required_permissions if not role_has_permission(user.role, permission)]
    if missing:
        raise TelegramApprovalDenied(
            "current_permission_missing",
            "لا يملك مستخدم النظام المرتبط الصلاحية المطلوبة.",
        )
    return organization, user, authorization


def _erp_for_organization(db: Session, organization_id: int):
    connection = (
        db.query(ERPConnection)
        .filter(
            ERPConnection.organization_id == organization_id,
            ERPConnection.is_active.is_(True),
        )
        .order_by(ERPConnection.id.asc())
        .first()
    )
    if connection is None or not connection.encrypted_secret_ref:
        raise TelegramApprovalDenied(
            "erp_connection_missing",
            "لا يوجد اتصال ERP نشط لهذه المؤسسة.",
        )
    try:
        secret = json.loads(decrypt_value(connection.encrypted_secret_ref))
        username = str(secret["username"])
        password = str(secret["password"])
    except Exception as exc:
        raise TelegramApprovalDenied(
            "erp_secret_unavailable",
            "تعذر فتح بيانات اتصال ERP بصورة آمنة.",
        ) from exc
    erp = get_erp_provider(
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=username,
        password=password,
    )
    return connection, erp, username


def _company_id(erp: Any, username: str) -> int | None:
    users = erp.execute_kw(
        "res.users",
        "search_read",
        [[["login", "=", username]]],
        {"fields": ["company_id"], "limit": 1},
    )
    company = users[0].get("company_id") if users else None
    if isinstance(company, (list, tuple)) and company:
        return int(company[0])
    if isinstance(company, int):
        return company
    return None


def _search_account(
    erp: Any,
    company_id: int | None,
    *,
    account_type: str | None = None,
    name_contains: str | None = None,
) -> dict[str, Any] | None:
    domain: list[Any] = []
    if account_type:
        domain.append(("account_type", "=", account_type))
    if name_contains:
        domain.append(("name", "ilike", name_contains))
    if company_id:
        domain.append(("company_ids", "in", [company_id]))
    rows = erp.execute_kw(
        "account.account",
        "search_read",
        [domain],
        {"fields": ["id", "name", "code"], "limit": 1},
    )
    return rows[0] if rows else None


def _account_label(account: dict[str, Any]) -> str:
    code = str(account.get("code") or "").strip()
    name = str(account.get("name") or "").strip()
    return f"{code} {name}".strip()


def _search_journal(erp: Any, company_id: int | None, journal_type: str) -> dict[str, Any] | None:
    domain: list[Any] = [("type", "=", journal_type)]
    if company_id:
        domain.append(("company_id", "=", company_id))
    rows = erp.execute_kw(
        "account.journal",
        "search_read",
        [domain],
        {"fields": ["id", "name", "default_account_id"], "limit": 1},
    )
    return rows[0] if rows else None


def _resolve_partner(erp: Any, partner_name: str) -> tuple[int | None, str]:
    normalized = (partner_name or "").strip()
    if not normalized:
        return None, ""
    rows = erp.execute_kw(
        "res.partner",
        "search_read",
        [[["active", "=", True], ["name", "ilike", normalized]]],
        {"fields": ["id", "name"], "limit": 1},
    )
    if not rows:
        return None, normalized
    return int(rows[0]["id"]), str(rows[0].get("name") or normalized)


def _classify(document_class: str, filename: str, raw_text: str) -> str:
    blob = f"{document_class} {filename} {raw_text}".lower()
    if any(term in blob for term in ("payroll", "salary", "مسير", "رواتب")):
        return "payroll"
    if any(term in blob for term in ("bank", "statement", "receipt", "كشف", "إيصال", "ايصال", "إشعار")):
        return "bank"
    if any(term in blob for term in ("invoice", "bill", "فاتورة")):
        return "invoice"
    return "general"


def build_accounting_proposal(
    db: Session,
    context: TelegramSecurityContext,
    *,
    filename: str,
    document_class: str,
    amount: Any,
    transaction_date: str,
    partner_name: str,
    raw_text: str,
    source: str,
) -> dict[str, Any]:
    """Build a tenant-scoped balanced proposal without importing any API route."""
    if source != "telegram":
        raise TelegramApprovalDenied("invalid_source")
    _validate_actor(db, context, ("upload_documents", "create_entries"))
    safe_filename = Path(filename or "document").name[:500]
    safe_amount = _safe_amount(amount)
    connection, erp, username = _erp_for_organization(db, context.organization_id)
    company_id = _company_id(erp, username)
    partner_id, resolved_partner_name = _resolve_partner(erp, partner_name)

    expense = _search_account(erp, company_id, account_type="expense")
    payable = _search_account(erp, company_id, account_type="liability_payable")
    suspense = _search_account(erp, company_id, name_contains="suspense") or _search_account(
        erp, company_id, name_contains="clearing"
    )
    fallback = expense or _search_account(erp, company_id)
    if fallback is None:
        raise TelegramApprovalDenied("account_mapping_unavailable", "تعذر تحديد حسابات القيد في Odoo.")
    expense = expense or fallback
    payable = payable or fallback
    suspense = suspense or fallback

    category = _classify(document_class, safe_filename, raw_text)
    debit_account = expense
    credit_account = payable if category in {"invoice", "payroll"} else suspense
    journal_type = "general"
    journal_name = "Miscellaneous Operations"

    if category == "bank":
        journal = _search_journal(erp, company_id, "bank")
        default_account = journal.get("default_account_id") if journal else None
        bank_account_id = default_account[0] if isinstance(default_account, (list, tuple)) and default_account else None
        bank_account_name = default_account[1] if isinstance(default_account, (list, tuple)) and len(default_account) > 1 else "Bank"
        if bank_account_id:
            credit_account = {"id": bank_account_id, "name": bank_account_name, "code": ""}
        journal_type = "bank"
        journal_name = str(journal.get("name") or "Bank") if journal else "Bank"

    amount_float = float(safe_amount)
    labels = {
        "invoice": (f"فاتورة من {safe_filename}", f"التزام مورد من {safe_filename}"),
        "payroll": (f"مصروف رواتب من {safe_filename}", f"رواتب مستحقة من {safe_filename}"),
        "bank": (f"عملية بنكية من {safe_filename}", f"حركة البنك من {safe_filename}"),
        "general": (f"تسجيل مستند {safe_filename}", f"القيد المقابل للمستند {safe_filename}"),
    }
    debit_label, credit_label = labels[category]
    lines = [
        {
            "account_id": int(debit_account["id"]),
            "account_name": _account_label(debit_account),
            "debit": amount_float,
            "credit": 0.0,
            "name": debit_label,
            "partner_id": partner_id,
        },
        {
            "account_id": int(credit_account["id"]),
            "account_name": _account_label(credit_account),
            "debit": 0.0,
            "credit": amount_float,
            "name": credit_label,
            "partner_id": partner_id,
        },
    ]
    return {
        "schema_version": 1,
        "source": source,
        "filename": safe_filename,
        "document_class": category,
        "amount": amount_float,
        "date": transaction_date,
        "partner_name": resolved_partner_name or (partner_name or "")[:255],
        "partner_id": partner_id,
        "raw_text": (raw_text or "")[:4000],
        "journal_type": journal_type,
        "journal_name": journal_name,
        "erp_connection_id": connection.id,
        "lines": lines,
    }


def create_approval_request(
    db: Session,
    context: TelegramSecurityContext,
    *,
    proposal: dict[str, Any],
    file_path: str | None,
    source: str,
) -> ApprovalCreationResult:
    _validate_actor(db, context, ("upload_documents", "create_entries"))
    if source != "telegram" or proposal.get("source") != source:
        raise TelegramApprovalDenied("source_mismatch")
    proposal = json.loads(json.dumps(proposal, ensure_ascii=False, allow_nan=False))
    proposal["file_sha256"] = _file_sha256(file_path)
    token = secrets.token_urlsafe(18)
    token_hash = _hash_token(token)
    expires_at = _utcnow() + timedelta(seconds=settings.TELEGRAM_APPROVAL_TTL_SECONDS)
    content_hash = _content_hash_for_values(
        organization_id=context.organization_id,
        authorization_id=context.authorization_id,
        telegram_user_id=context.telegram_user_id,
        telegram_chat_id=context.telegram_chat_id,
        system_user_id=context.system_user_id,
        source=source,
        payload=proposal,
    )
    operation = TelegramApprovalOperation(
        organization_id=context.organization_id,
        authorization_id=context.authorization_id,
        telegram_user_id=context.telegram_user_id,
        telegram_chat_id=context.telegram_chat_id,
        system_user_id=context.system_user_id,
        source=source,
        status="pending",
        content_hash=content_hash,
        approval_token_hash=token_hash,
        payload=proposal,
        file_path=file_path,
        expires_at=expires_at,
    )
    db.add(operation)
    db.commit()
    db.refresh(operation)
    record_telegram_event(
        db,
        "telegram_approval_created",
        context=context,
        details={
            "operation_id": operation.id,
            "source": source,
            "content_hash_prefix": content_hash[:12],
            "expires_at": expires_at.isoformat(),
        },
    )
    return ApprovalCreationResult(operation.id, token, expires_at, proposal)


def create_document_approval(
    db: Session,
    context: TelegramSecurityContext,
    *,
    filename: str,
    document_class: str,
    amount: Any,
    transaction_date: str,
    partner_name: str,
    raw_text: str,
    file_path: str | None,
    source: str = "telegram",
) -> ApprovalCreationResult:
    proposal = build_accounting_proposal(
        db,
        context,
        filename=filename,
        document_class=document_class,
        amount=amount,
        transaction_date=transaction_date,
        partner_name=partner_name,
        raw_text=raw_text,
        source=source,
    )
    return create_approval_request(
        db,
        context,
        proposal=proposal,
        file_path=file_path,
        source=source,
    )


def build_callback_data(action: str, operation_id: int, token: str) -> str:
    if action not in {"approve", "cancel"}:
        raise ValueError("Unsupported callback action")
    value = f"tg1:{action}:{operation_id}:{token}"
    if len(value.encode("utf-8")) > 64:
        raise ValueError("Telegram callback data exceeds 64 bytes")
    return value


def parse_callback_data(value: str | None) -> tuple[str, int, str] | None:
    if not value:
        return None
    parts = value.split(":", 3)
    if len(parts) != 4 or parts[0] != "tg1" or parts[1] not in {"approve", "cancel"}:
        return None
    try:
        operation_id = int(parts[2])
    except ValueError:
        return None
    if operation_id <= 0 or not parts[3]:
        return None
    return parts[1], operation_id, parts[3]


def _load_and_validate_pending(
    db: Session,
    context: TelegramSecurityContext,
    operation_id: int,
    token: str,
    *,
    required_permissions: Iterable[str],
) -> TelegramApprovalOperation:
    _validate_actor(db, context, required_permissions)
    operation = (
        db.query(TelegramApprovalOperation)
        .filter(TelegramApprovalOperation.id == operation_id)
        .first()
    )
    if operation is None:
        raise TelegramApprovalDenied("approval_not_found")
    if (
        operation.organization_id != context.organization_id
        or operation.authorization_id != context.authorization_id
        or operation.telegram_user_id != context.telegram_user_id
        or operation.telegram_chat_id != context.telegram_chat_id
        or operation.system_user_id != context.system_user_id
        or operation.source != "telegram"
    ):
        raise TelegramApprovalDenied("approval_actor_mismatch", "هذه الموافقة لا تخص هذا المستخدم.")
    if operation.status != "pending":
        raise TelegramApprovalDenied("approval_not_pending", "تم استخدام أو إلغاء هذه الموافقة مسبقًا.")
    if operation.revoked_at is not None:
        raise TelegramApprovalDenied("approval_revoked")
    expected_token_hash = _hash_token(token)
    if not hmac.compare_digest(operation.approval_token_hash, expected_token_hash):
        raise TelegramApprovalDenied("approval_token_invalid")
    if not hmac.compare_digest(operation.content_hash, _content_hash_for_row(operation)):
        raise TelegramApprovalDenied("approval_content_tampered")
    now = _utcnow()
    if operation.expires_at <= now:
        db.query(TelegramApprovalOperation).filter(
            TelegramApprovalOperation.id == operation.id,
            TelegramApprovalOperation.status == "pending",
        ).update(
            {"status": "expired", "consumed_at": now, "failure_code": "approval_expired"},
            synchronize_session=False,
        )
        db.commit()
        raise TelegramApprovalDenied("approval_expired", "انتهت صلاحية الموافقة. أعد إرسال المستند.")
    return operation


def _claim_operation_atomically(
    db: Session,
    operation: TelegramApprovalOperation,
    token: str,
) -> TelegramApprovalOperation:
    now = _utcnow()
    expected_token_hash = _hash_token(token)
    updated = (
        db.query(TelegramApprovalOperation)
        .filter(
            TelegramApprovalOperation.id == operation.id,
            TelegramApprovalOperation.status == "pending",
            TelegramApprovalOperation.approval_token_hash == expected_token_hash,
            TelegramApprovalOperation.content_hash == operation.content_hash,
            TelegramApprovalOperation.expires_at > now,
            TelegramApprovalOperation.revoked_at.is_(None),
        )
        .update(
            {"status": "processing", "consumed_at": now},
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        raise TelegramApprovalDenied("approval_claim_conflict", "تم استخدام هذه الموافقة بالفعل.")
    claimed = db.query(TelegramApprovalOperation).filter(TelegramApprovalOperation.id == operation.id).first()
    if claimed is None or not hmac.compare_digest(claimed.content_hash, _content_hash_for_row(claimed)):
        if claimed is not None:
            claimed.status = "failed"
            claimed.failure_code = "content_hash_changed_after_claim"
            db.commit()
        raise TelegramApprovalDenied("approval_content_tampered")
    return claimed


def _verify_file_integrity(operation: TelegramApprovalOperation) -> None:
    expected = operation.payload.get("file_sha256")
    if not expected:
        return
    actual = _file_sha256(operation.file_path)
    if not actual or not hmac.compare_digest(str(expected), actual):
        raise TelegramApprovalDenied("approval_file_tampered", "تغير الملف بعد إنشاء الموافقة.")


def _balanced_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    lines = payload.get("lines")
    if not isinstance(lines, list) or len(lines) < 2:
        raise TelegramApprovalDenied("invalid_journal_lines")
    debit_total = 0.0
    credit_total = 0.0
    normalized: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            raise TelegramApprovalDenied("invalid_journal_lines")
        debit = float(line.get("debit") or 0.0)
        credit = float(line.get("credit") or 0.0)
        if not math.isfinite(debit) or not math.isfinite(credit) or debit < 0 or credit < 0:
            raise TelegramApprovalDenied("invalid_journal_lines")
        if (debit > 0) == (credit > 0):
            raise TelegramApprovalDenied("invalid_journal_lines")
        normalized.append(
            {
                "account_id": int(line["account_id"]),
                "name": str(line.get("name") or "Telegram accounting operation")[:255],
                "debit": debit,
                "credit": credit,
                "partner_id": line.get("partner_id") or False,
            }
        )
        debit_total += debit
        credit_total += credit
    if abs(debit_total - credit_total) > 0.005 or debit_total <= 0:
        raise TelegramApprovalDenied("journal_not_balanced")
    return normalized


def _post_claimed_operation(db: Session, operation: TelegramApprovalOperation) -> ApprovalPostingResult:
    _verify_file_integrity(operation)
    connection, erp, username = _erp_for_organization(db, operation.organization_id)
    company_id = _company_id(erp, username)
    payload = operation.payload
    lines = _balanced_lines(payload)
    journal_type = str(payload.get("journal_type") or "general")
    journal = _search_journal(erp, company_id, journal_type) or _search_journal(erp, company_id, "general")
    move_vals: dict[str, Any] = {
        "move_type": "entry",
        "date": str(payload.get("date") or _utcnow().date().isoformat()),
        "ref": f"TG#{operation.id}: {str(payload.get('filename') or 'document')[:180]}",
        "line_ids": [(0, 0, line) for line in lines],
    }
    if journal:
        move_vals["journal_id"] = int(journal["id"])
    move_id = int(erp.execute_kw("account.move", "create", [move_vals]))
    erp.execute_kw("account.move", "action_post", [[move_id]])

    attachment_id: int | None = None
    path = Path(operation.file_path) if operation.file_path else None
    if path and path.is_file():
        with path.open("rb") as source:
            encoded = base64.b64encode(source.read()).decode("ascii")
        attachment_id = int(
            erp.execute_kw(
                "ir.attachment",
                "create",
                [{
                    "name": str(payload.get("filename") or path.name)[:500],
                    "type": "binary",
                    "datas": encoded,
                    "res_model": "account.move",
                    "res_id": move_id,
                }],
            )
        )

    move_name = f"MOVE/{move_id}"
    try:
        rows = erp.execute_kw("account.move", "read", [[move_id]], {"fields": ["name"]})
        if rows and rows[0].get("name"):
            move_name = str(rows[0]["name"])
    except Exception:
        pass
    return ApprovalPostingResult(
        operation_id=operation.id,
        move_id=move_id,
        move_name=move_name,
        attachment_id=attachment_id,
        odoo_url=f"{connection.base_url.rstrip('/')}/web#id={move_id}&model=account.move&view_type=form",
    )


def consume_and_post_approval(
    db: Session,
    context: TelegramSecurityContext,
    *,
    operation_id: int,
    token: str,
) -> ApprovalPostingResult:
    operation = _load_and_validate_pending(
        db,
        context,
        operation_id,
        token,
        required_permissions=("post_odoo_entries",),
    )
    claimed = _claim_operation_atomically(db, operation, token)
    record_telegram_event(
        db,
        "telegram_approval_claimed",
        context=context,
        details={"operation_id": claimed.id, "content_hash_prefix": claimed.content_hash[:12]},
    )
    try:
        _validate_actor(db, context, ("post_odoo_entries",))
        result = _post_claimed_operation(db, claimed)
        claimed = db.query(TelegramApprovalOperation).filter(TelegramApprovalOperation.id == claimed.id).first()
        if claimed is None or claimed.status != "processing":
            raise TelegramApprovalDenied("approval_state_changed_during_post")
        claimed.status = "posted"
        claimed.posted_move_id = result.move_id
        claimed.attachment_id = result.attachment_id
        db.commit()
        record_telegram_event(
            db,
            "telegram_approval_posted",
            context=context,
            details={
                "operation_id": result.operation_id,
                "move_id": result.move_id,
                "attachment_id": result.attachment_id,
            },
        )
        _delete_terminal_file(claimed.file_path)
        return result
    except Exception as exc:
        db.rollback()
        failed = db.query(TelegramApprovalOperation).filter(TelegramApprovalOperation.id == operation_id).first()
        if failed is not None and failed.status == "processing":
            failed.status = "failed"
            failed.failure_code = getattr(exc, "reason", "odoo_post_failed")[:100]
            db.commit()
        record_telegram_event(
            db,
            "telegram_approval_post_failed",
            context=context,
            details={"operation_id": operation_id, "failure_code": getattr(exc, "reason", "odoo_post_failed")},
        )
        if isinstance(exc, TelegramApprovalDenied):
            raise
        raise TelegramApprovalDenied("odoo_post_failed", "تعذر ترحيل القيد إلى Odoo بصورة آمنة.") from exc


def cancel_approval(
    db: Session,
    context: TelegramSecurityContext,
    *,
    operation_id: int,
    token: str,
) -> None:
    operation = _load_and_validate_pending(
        db,
        context,
        operation_id,
        token,
        required_permissions=("view_financials",),
    )
    now = _utcnow()
    updated = (
        db.query(TelegramApprovalOperation)
        .filter(
            TelegramApprovalOperation.id == operation.id,
            TelegramApprovalOperation.status == "pending",
            TelegramApprovalOperation.approval_token_hash == _hash_token(token),
            TelegramApprovalOperation.content_hash == operation.content_hash,
        )
        .update(
            {"status": "cancelled", "consumed_at": now, "revoked_at": now},
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        raise TelegramApprovalDenied("approval_cancel_conflict", "تم استخدام هذه الموافقة بالفعل.")
    record_telegram_event(
        db,
        "telegram_approval_cancelled",
        context=context,
        details={"operation_id": operation.id},
    )
    _delete_terminal_file(operation.file_path)


def _delete_terminal_file(file_path: str | None) -> None:
    if not file_path:
        return
    try:
        Path(file_path).unlink(missing_ok=True)
    except Exception:
        pass


def revoke_actor_pending_operations(
    db: Session,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    reason: str,
) -> int:
    rows = (
        db.query(TelegramApprovalOperation)
        .filter(
            TelegramApprovalOperation.telegram_chat_id == telegram_chat_id,
            TelegramApprovalOperation.telegram_user_id == telegram_user_id,
            TelegramApprovalOperation.status == "pending",
        )
        .all()
    )
    now = _utcnow()
    for row in rows:
        row.status = "revoked"
        row.revoked_at = now
        row.failure_code = reason[:100]
    db.commit()
    for row in rows:
        _delete_terminal_file(row.file_path)
    return len(rows)


def revoke_all_pending_operations(db: Session, *, reason: str) -> int:
    rows = db.query(TelegramApprovalOperation).filter(TelegramApprovalOperation.status == "pending").all()
    now = _utcnow()
    for row in rows:
        row.status = "revoked"
        row.revoked_at = now
        row.failure_code = reason[:100]
    db.commit()
    for row in rows:
        _delete_terminal_file(row.file_path)
    return len(rows)


def count_pending_operations(db: Session) -> int:
    return int(
        db.query(TelegramApprovalOperation)
        .filter(TelegramApprovalOperation.status == "pending")
        .count()
    )
