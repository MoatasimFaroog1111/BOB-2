"""Security regression tests for durable Telegram accounting approvals."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta

import pytest

from app.models.core import (
    ERPConnection,
    Organization,
    TelegramApprovalOperation,
    TelegramAuthorization,
    User,
)
from app.security.auth import hash_password
from app.security.encryption import encrypt_value
from app.services import telegram_bot
from app.services.telegram_accounting_service import (
    TelegramApprovalDenied,
    build_callback_data,
    cancel_approval,
    consume_and_post_approval,
    create_approval_request,
    parse_callback_data,
)
from app.services.telegram_security import TelegramSecurityContext


class FakeERP:
    def __init__(self):
        self.created_move_values = None
        self.posted_ids: list[int] = []

    def execute_kw(self, model, method, args, kwargs=None):
        kwargs = kwargs or {}
        if model == "res.users" and method == "search_read":
            return [{"company_id": [7, "Test Company"]}]
        if model == "account.journal" and method == "search_read":
            return [{"id": 41, "name": "Miscellaneous Operations", "default_account_id": None}]
        if model == "account.move" and method == "create":
            self.created_move_values = args[0]
            return 501
        if model == "account.move" and method == "action_post":
            self.posted_ids.extend(args[0])
            return True
        if model == "account.move" and method == "read":
            return [{"id": 501, "name": "MISC/2026/0501"}]
        if model == "ir.attachment" and method == "create":
            return 901
        raise AssertionError(f"Unexpected ERP call: {model}.{method} {args} {kwargs}")


def _seed_actor(db, *, org_id=1, user_id=1, auth_id=1, telegram_user_id=1001, chat_id=2001, role="owner"):
    organization = Organization(
        id=org_id,
        name=f"Org {org_id}",
        legal_name=f"Organization {org_id}",
        country="SA",
        is_active=True,
    )
    user = User(
        id=user_id,
        organization_id=org_id,
        email=f"user{user_id}@example.com",
        full_name=f"User {user_id}",
        role=role,
        hashed_password=hash_password("Temporary-Test-Password-Only"),
        is_active=True,
    )
    db.add_all([organization, user])
    db.commit()
    authorization = TelegramAuthorization(
        id=auth_id,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=chat_id,
        organization_id=org_id,
        system_user_id=user_id,
        created_by_user_id=user_id,
        allow_group_chats=False,
        is_active=True,
    )
    connection = ERPConnection(
        id=org_id,
        organization_id=org_id,
        provider="odoo",
        base_url=f"https://odoo-{org_id}.example.com",
        database_name=f"db{org_id}",
        auth_type="password",
        encrypted_secret_ref=encrypt_value(
            json.dumps({"username": f"erp{org_id}@example.com", "password": "test-only"})
        ),
        is_active=True,
    )
    db.add_all([authorization, connection])
    db.commit()
    return TelegramSecurityContext(
        authorization_id=auth_id,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=chat_id,
        chat_type="private",
        organization_id=org_id,
        system_user_id=user_id,
        system_user_email=user.email,
        system_user_role=user.role,
    )


def _proposal(amount=100.0):
    return {
        "schema_version": 1,
        "source": "telegram",
        "filename": "invoice.pdf",
        "document_class": "general",
        "amount": amount,
        "date": "2026-07-14",
        "partner_name": "",
        "partner_id": None,
        "raw_text": "test document",
        "journal_type": "general",
        "journal_name": "Miscellaneous Operations",
        "erp_connection_id": 1,
        "lines": [
            {
                "account_id": 101,
                "account_name": "101 Expense",
                "debit": amount,
                "credit": 0.0,
                "name": "Expense",
                "partner_id": None,
            },
            {
                "account_id": 202,
                "account_name": "202 Clearing",
                "debit": 0.0,
                "credit": amount,
                "name": "Clearing",
                "partner_id": None,
            },
        ],
    }


def _create(db, context, amount=100.0):
    return create_approval_request(
        db,
        context,
        proposal=_proposal(amount),
        file_path=None,
        source="telegram",
    )


def test_telegram_bot_has_no_fastapi_erp_route_dependency():
    source = inspect.getsource(telegram_bot)
    assert "app.api.v1.erp" not in source
    assert "propose_transaction" not in source
    assert "register_document" not in source


def test_callback_token_is_compact_parseable_and_not_stored_in_plaintext(db):
    context = _seed_actor(db)
    approval = _create(db, context)
    callback = build_callback_data("approve", approval.operation_id, approval.approval_token)

    assert len(callback.encode("utf-8")) <= 64
    assert parse_callback_data(callback) == (
        "approve",
        approval.operation_id,
        approval.approval_token,
    )
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    assert row.approval_token_hash != approval.approval_token
    assert len(row.approval_token_hash) == 64
    assert row.content_hash


def test_approval_posts_once_and_replay_is_rejected(db, monkeypatch):
    context = _seed_actor(db)
    approval = _create(db, context)
    fake = FakeERP()
    monkeypatch.setattr(
        "app.services.telegram_accounting_service.get_erp_provider",
        lambda **kwargs: fake,
    )

    result = consume_and_post_approval(
        db,
        context,
        operation_id=approval.operation_id,
        token=approval.approval_token,
    )

    assert result.move_id == 501
    assert fake.posted_ids == [501]
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    assert row.status == "posted"
    assert row.consumed_at is not None
    assert row.posted_move_id == 501

    with pytest.raises(TelegramApprovalDenied) as replay:
        consume_and_post_approval(
            db,
            context,
            operation_id=approval.operation_id,
            token=approval.approval_token,
        )
    assert replay.value.reason == "approval_not_pending"
    assert fake.posted_ids == [501]


def test_wrong_token_is_rejected_without_consuming_operation(db):
    context = _seed_actor(db)
    approval = _create(db, context)

    with pytest.raises(TelegramApprovalDenied) as denied:
        consume_and_post_approval(
            db,
            context,
            operation_id=approval.operation_id,
            token="wrong-token",
        )
    assert denied.value.reason == "approval_token_invalid"
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    assert row.status == "pending"
    assert row.consumed_at is None


def test_expired_approval_is_terminal_and_cannot_post(db):
    context = _seed_actor(db)
    approval = _create(db, context)
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    with pytest.raises(TelegramApprovalDenied) as denied:
        consume_and_post_approval(
            db,
            context,
            operation_id=approval.operation_id,
            token=approval.approval_token,
        )
    assert denied.value.reason == "approval_expired"
    db.expire_all()
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    assert row.status == "expired"
    assert row.consumed_at is not None


def test_content_tampering_is_detected_before_claim(db):
    context = _seed_actor(db)
    approval = _create(db, context)
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    tampered = dict(row.payload)
    tampered["amount"] = 999.0
    row.payload = tampered
    db.commit()

    with pytest.raises(TelegramApprovalDenied) as denied:
        consume_and_post_approval(
            db,
            context,
            operation_id=approval.operation_id,
            token=approval.approval_token,
        )
    assert denied.value.reason == "approval_content_tampered"


def test_different_telegram_actor_cannot_use_approval(db):
    context = _seed_actor(db)
    approval = _create(db, context)
    other = _seed_actor(
        db,
        org_id=2,
        user_id=2,
        auth_id=2,
        telegram_user_id=1002,
        chat_id=2002,
    )

    with pytest.raises(TelegramApprovalDenied) as denied:
        consume_and_post_approval(
            db,
            other,
            operation_id=approval.operation_id,
            token=approval.approval_token,
        )
    assert denied.value.reason == "approval_actor_mismatch"


def test_role_reduction_takes_effect_before_posting(db):
    context = _seed_actor(db)
    approval = _create(db, context)
    user = db.query(User).filter_by(id=context.system_user_id).one()
    user.role = "viewer"
    db.commit()

    with pytest.raises(TelegramApprovalDenied) as denied:
        consume_and_post_approval(
            db,
            context,
            operation_id=approval.operation_id,
            token=approval.approval_token,
        )
    assert denied.value.reason == "current_permission_missing"
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    assert row.status == "pending"


def test_cancellation_consumes_token_and_blocks_replay(db):
    context = _seed_actor(db)
    approval = _create(db, context)

    cancel_approval(
        db,
        context,
        operation_id=approval.operation_id,
        token=approval.approval_token,
    )
    row = db.query(TelegramApprovalOperation).filter_by(id=approval.operation_id).one()
    assert row.status == "cancelled"
    assert row.revoked_at is not None

    with pytest.raises(TelegramApprovalDenied) as replay:
        cancel_approval(
            db,
            context,
            operation_id=approval.operation_id,
            token=approval.approval_token,
        )
    assert replay.value.reason == "approval_not_pending"


def test_admin_approval_list_is_tenant_scoped_and_revoke_is_atomic(client, auth_headers, db):
    context = TelegramSecurityContext(
        authorization_id=1,
        telegram_user_id=1001,
        telegram_chat_id=2001,
        chat_type="private",
        organization_id=1,
        system_user_id=1,
        system_user_email="test@guardian-ai.com",
        system_user_role="owner",
    )
    authorization = TelegramAuthorization(
        id=1,
        telegram_user_id=1001,
        telegram_chat_id=2001,
        organization_id=1,
        system_user_id=1,
        created_by_user_id=1,
        allow_group_chats=False,
        is_active=True,
    )
    db.add(authorization)
    db.commit()
    own = _create(db, context)

    org2 = Organization(id=2, name="Org 2", legal_name="Org 2", country="SA", is_active=True)
    user2 = User(
        id=2,
        organization_id=2,
        email="other@example.com",
        full_name="Other",
        role="owner",
        hashed_password=hash_password("Temporary-Test-Password-Only"),
        is_active=True,
    )
    db.add_all([org2, user2])
    db.commit()
    auth2 = TelegramAuthorization(
        id=2,
        telegram_user_id=1002,
        telegram_chat_id=2002,
        organization_id=2,
        system_user_id=2,
        created_by_user_id=2,
        allow_group_chats=False,
        is_active=True,
    )
    db.add(auth2)
    db.commit()
    other_context = TelegramSecurityContext(
        authorization_id=2,
        telegram_user_id=1002,
        telegram_chat_id=2002,
        chat_type="private",
        organization_id=2,
        system_user_id=2,
        system_user_email="other@example.com",
        system_user_role="owner",
    )
    _create(db, other_context)

    listing = client.get("/api/v1/telegram/approval-operations", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert [row["id"] for row in rows] == [own.operation_id]
    assert all(row["organization_id"] == 1 for row in rows)

    revoke = client.post(
        f"/api/v1/telegram/approval-operations/{own.operation_id}/revoke",
        headers=auth_headers,
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "revoked"

    replay = client.post(
        f"/api/v1/telegram/approval-operations/{own.operation_id}/revoke",
        headers=auth_headers,
    )
    assert replay.status_code == 409
