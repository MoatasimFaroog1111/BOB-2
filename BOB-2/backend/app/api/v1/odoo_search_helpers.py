"""Shared read-only Odoo helpers used by local accounting searches."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value
from app.security.tenant_scope import current_organization_id

BASE_LINE_FIELDS = [
    "id",
    "move_id",
    "date",
    "account_id",
    "partner_id",
    "name",
    "ref",
    "debit",
    "credit",
    "balance",
    "company_id",
]

BASE_MOVE_FIELDS = [
    "id",
    "name",
    "date",
    "ref",
    "payment_reference",
    "narration",
    "invoice_origin",
    "partner_id",
    "journal_id",
    "state",
    "move_type",
    "company_id",
]

TEXT_FIELD_HINTS = {
    "name",
    "description",
    "label",
    "memo",
    "narration",
    "reference",
    "ref",
    "payment",
    "communication",
    "partner",
    "customer",
    "vendor",
    "supplier",
    "check",
    "cheque",
    "chq",
    "شيك",
}

TEXT_FIELD_TYPES = {
    "char",
    "text",
    "html",
    "selection",
    "reference",
    "many2one",
}


def value_text(value: Any) -> str:
    if value in (None, False):
        return ""
    if isinstance(value, (list, tuple)):
        if len(value) > 1:
            return str(value[1] or "")
        if value:
            return str(value[0] or "")
        return ""
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values() if item)

    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", text).strip()


def many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    if isinstance(value, int):
        return value
    return None


def read_fields(erp: Any, model: str) -> dict[str, dict[str, Any]]:
    try:
        result = erp.execute_kw(
            model,
            "fields_get",
            [],
            {"attributes": ["string", "type"]},
        )
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def select_fields(
    metadata: dict[str, dict[str, Any]],
    base_fields: list[str],
    *,
    max_fields: int = 45,
) -> list[str]:
    selected: list[str] = ["id"]

    for field_name in base_fields:
        if field_name == "id" or not metadata or field_name in metadata:
            if field_name not in selected:
                selected.append(field_name)

    for field_name, definition in metadata.items():
        field_type = str(definition.get("type") or "")
        label = str(definition.get("string") or "")
        searchable_text = f"{field_name} {label}".lower()
        if field_type not in TEXT_FIELD_TYPES:
            continue
        if not any(hint in searchable_text for hint in TEXT_FIELD_HINTS):
            continue
        if field_name not in selected:
            selected.append(field_name)
        if len(selected) >= max_fields:
            break

    return selected


def existing_fields(
    metadata: dict[str, dict[str, Any]],
    preferred: list[str],
) -> list[str]:
    if not metadata:
        return list(preferred)
    return [field for field in preferred if field in metadata]


def read_connection(db_session: Session):
    connection = (
        db_session.query(ERPConnection)
        .filter(
            ERPConnection.organization_id == current_organization_id(required=True),
            ERPConnection.is_active.is_(True),
        )
        .first()
    )
    if not connection:
        raise RuntimeError("No active ERP connection found.")

    credentials = json.loads(decrypt_value(connection.encrypted_secret_ref))
    erp = get_erp_provider(
        provider=connection.provider,
        url=connection.base_url,
        db=connection.database_name or "",
        username=credentials.get("username"),
        password=credentials.get("password"),
    )
    return connection, erp


def read_moves(
    erp: Any,
    move_ids: list[int],
    fields: list[str],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for start in range(0, len(move_ids), 200):
        chunk = move_ids[start : start + 200]
        if not chunk:
            continue
        moves = erp.execute_kw(
            "account.move",
            "search_read",
            [[['id', 'in', chunk]]],
            {"fields": fields, "limit": len(chunk)},
        )
        for move in moves or []:
            move_id = move.get("id")
            if isinstance(move_id, int):
                result[move_id] = move
    return result


def read_accounts(
    erp: Any,
    account_ids: list[int],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for start in range(0, len(account_ids), 200):
        chunk = account_ids[start : start + 200]
        if not chunk:
            continue
        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [[['id', 'in', chunk]]],
            {"fields": ["id", "code", "name"], "limit": len(chunk)},
        )
        for account in accounts or []:
            account_id = account.get("id")
            if isinstance(account_id, int):
                result[account_id] = account
    return result
