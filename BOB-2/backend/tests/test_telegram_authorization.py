"""Security regression tests for Telegram identity, tenant, chat, and RBAC binding."""

import pytest

from app.core.config import settings
from app.models.core import AuditLog, Organization, TelegramAuthorization, User
from app.security.auth import hash_password
from app.services import telegram_bot
from app.services.telegram_security import (
    TelegramAuthorizationDenied,
    TelegramSecurityContext,
    authorize_telegram_actor,
)


def _seed_identity(
    db,
    *,
    organization_id: int = 1,
    user_id: int = 1,
    role: str = "owner",
    telegram_user_id: int = 10001,
    telegram_chat_id: int = 10001,
    allow_group_chats: bool = False,
    authorization_active: bool = True,
    organization_active: bool = True,
    user_active: bool = True,
):
    organization = Organization(
        id=organization_id,
        name=f"Org {organization_id}",
        legal_name=f"Org {organization_id}",
        country="SA",
        is_active=organization_active,
    )
    user = User(
        id=user_id,
        organization_id=organization_id,
        email=f"user{user_id}@example.com",
        full_name=f"User {user_id}",
        role=role,
        hashed_password=hash_password("Test@Pass1234!"),
        is_active=user_active,
    )
    db.add_all([organization, user])
    db.commit()
    authorization = TelegramAuthorization(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        organization_id=organization_id,
        system_user_id=user_id,
        created_by_user_id=user_id,
        allow_group_chats=allow_group_chats,
        is_active=authorization_active,
    )
    db.add(authorization)
    db.commit()
    db.refresh(authorization)
    return organization, user, authorization


def test_exact_actor_chat_pair_resolves_current_system_identity(db):
    _, user, authorization = _seed_identity(db)

    context = authorize_telegram_actor(
        db,
        telegram_user_id=10001,
        telegram_chat_id=10001,
        chat_type="private",
        required_permissions=("post_odoo_entries",),
        event_type="callback_query",
        update_id=7,
    )

    assert context.authorization_id == authorization.id
    assert context.organization_id == 1
    assert context.system_user_id == user.id
    assert context.system_user_role == "owner"
    assert context.pending_key == (10001, 10001)
    assert db.query(AuditLog).filter(AuditLog.action == "telegram_access_granted").count() == 1


def test_wrong_chat_is_rejected_and_audited(db):
    _seed_identity(db)

    with pytest.raises(TelegramAuthorizationDenied) as exc:
        authorize_telegram_actor(
            db,
            telegram_user_id=10001,
            telegram_chat_id=99999,
            chat_type="private",
            required_permissions=("view_financials",),
            event_type="message",
        )

    assert exc.value.reason == "actor_chat_not_allowlisted"
    denial = db.query(AuditLog).filter(AuditLog.action == "telegram_access_denied").first()
    assert denial is not None
    assert denial.organization_id == 1
    assert denial.user_id == 1


def test_current_database_role_controls_every_sensitive_operation(db):
    _, user, _ = _seed_identity(db, role="admin")
    authorize_telegram_actor(
        db,
        telegram_user_id=10001,
        telegram_chat_id=10001,
        chat_type="private",
        required_permissions=("post_odoo_entries",),
        event_type="callback_query",
    )

    user.role = "viewer"
    db.commit()

    with pytest.raises(TelegramAuthorizationDenied) as exc:
        authorize_telegram_actor(
            db,
            telegram_user_id=10001,
            telegram_chat_id=10001,
            chat_type="private",
            required_permissions=("post_odoo_entries",),
            event_type="callback_query",
        )
    assert exc.value.reason == "insufficient_system_permissions"


def test_group_chats_require_global_and_per_record_opt_in(db, monkeypatch):
    _seed_identity(
        db,
        telegram_user_id=20001,
        telegram_chat_id=-90001,
        allow_group_chats=True,
    )
    monkeypatch.setattr(settings, "TELEGRAM_ALLOW_GROUP_CHATS", False)
    with pytest.raises(TelegramAuthorizationDenied) as exc:
        authorize_telegram_actor(
            db,
            telegram_user_id=20001,
            telegram_chat_id=-90001,
            chat_type="supergroup",
            required_permissions=("view_financials",),
            event_type="message",
        )
    assert exc.value.reason == "group_chat_not_allowed"

    monkeypatch.setattr(settings, "TELEGRAM_ALLOW_GROUP_CHATS", True)
    context = authorize_telegram_actor(
        db,
        telegram_user_id=20001,
        telegram_chat_id=-90001,
        chat_type="supergroup",
        required_permissions=("view_financials",),
        event_type="message",
    )
    assert context.chat_type == "supergroup"


def test_inactive_authorization_user_and_organization_fail_closed(db):
    organization, user, authorization = _seed_identity(db)

    authorization.is_active = False
    db.commit()
    with pytest.raises(TelegramAuthorizationDenied) as inactive_authorization:
        authorize_telegram_actor(
            db,
            telegram_user_id=10001,
            telegram_chat_id=10001,
            chat_type="private",
            event_type="message",
        )
    assert inactive_authorization.value.reason == "authorization_inactive"

    authorization.is_active = True
    user.is_active = False
    db.commit()
    with pytest.raises(TelegramAuthorizationDenied) as inactive_user:
        authorize_telegram_actor(
            db,
            telegram_user_id=10001,
            telegram_chat_id=10001,
            chat_type="private",
            event_type="message",
        )
    assert inactive_user.value.reason == "linked_system_user_invalid"

    user.is_active = True
    organization.is_active = False
    db.commit()
    with pytest.raises(TelegramAuthorizationDenied) as inactive_org:
        authorize_telegram_actor(
            db,
            telegram_user_id=10001,
            telegram_chat_id=10001,
            chat_type="private",
            event_type="message",
        )
    assert inactive_org.value.reason == "organization_inactive_or_missing"


def test_pending_entries_are_bound_to_individual_actor():
    first = TelegramSecurityContext(
        authorization_id=1,
        telegram_user_id=10,
        telegram_chat_id=-500,
        chat_type="group",
        organization_id=1,
        system_user_id=1,
        system_user_email="first@example.com",
        system_user_role="owner",
    )
    second = TelegramSecurityContext(
        authorization_id=2,
        telegram_user_id=20,
        telegram_chat_id=-500,
        chat_type="group",
        organization_id=1,
        system_user_id=2,
        system_user_email="second@example.com",
        system_user_role="owner",
    )
    telegram_bot.PENDING_ENTRIES.clear()
    telegram_bot.PENDING_ENTRIES[first.pending_key] = {
        "telegram_user_id": first.telegram_user_id,
        "telegram_chat_id": first.telegram_chat_id,
        "organization_id": first.organization_id,
        "system_user_id": first.system_user_id,
        "authorization_id": first.authorization_id,
    }

    assert first.pending_key != second.pending_key
    assert telegram_bot.clear_pending_for_actor(second.telegram_chat_id, second.telegram_user_id) == 0
    assert first.pending_key in telegram_bot.PENDING_ENTRIES
    assert telegram_bot.clear_pending_for_actor(first.telegram_chat_id, first.telegram_user_id) == 1
    assert first.pending_key not in telegram_bot.PENDING_ENTRIES


def test_allowlist_api_is_tenant_scoped_and_soft_deactivates(
    client,
    auth_headers,
    db,
):
    create_response = client.post(
        "/api/v1/telegram/authorizations",
        headers=auth_headers,
        json={
            "telegram_user_id": 70001,
            "telegram_chat_id": 70001,
            "system_user_id": 1,
            "allow_group_chats": False,
            "is_active": True,
        },
    )
    assert create_response.status_code == 201, create_response.text
    record_id = create_response.json()["id"]
    assert create_response.json()["organization_id"] == 1
    assert create_response.json()["system_user_role"] == "owner"

    duplicate = client.post(
        "/api/v1/telegram/authorizations",
        headers=auth_headers,
        json={
            "telegram_user_id": 70001,
            "telegram_chat_id": 70001,
            "system_user_id": 1,
        },
    )
    assert duplicate.status_code == 409

    other_org = Organization(id=2, name="Other", legal_name="Other", country="SA", is_active=True)
    other_user = User(
        id=2,
        organization_id=2,
        email="other@example.com",
        full_name="Other User",
        role="owner",
        hashed_password=hash_password("Test@Pass1234!"),
        is_active=True,
    )
    db.add_all([other_org, other_user])
    db.commit()
    cross_tenant = client.post(
        "/api/v1/telegram/authorizations",
        headers=auth_headers,
        json={
            "telegram_user_id": 70002,
            "telegram_chat_id": 70002,
            "system_user_id": 2,
        },
    )
    assert cross_tenant.status_code == 404

    listed = client.get("/api/v1/telegram/authorizations", headers=auth_headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [record_id]

    deactivated = client.delete(
        f"/api/v1/telegram/authorizations/{record_id}",
        headers=auth_headers,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    authorization = db.query(TelegramAuthorization).filter(TelegramAuthorization.id == record_id).first()
    assert authorization is not None
    assert authorization.is_active is False
    assert (
        db.query(AuditLog)
        .filter(AuditLog.action == "telegram_authorization_deactivated")
        .count()
        == 1
    )
