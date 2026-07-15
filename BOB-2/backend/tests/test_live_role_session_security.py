"""Regression tests for live database roles and security-version sessions."""

from app.models.core import AuthSession, Organization, User
from app.security.auth import (
    create_access_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    new_token_id,
)


def _login(client, seeded_user):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_user["email"],
            "password": seeded_user["password"],
        },
        headers={"User-Agent": "live-role-test"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _authorization(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "User-Agent": "live-role-test"}


def test_login_binds_tokens_and_session_to_current_security_version(
    client,
    seeded_user,
    db,
):
    login = _login(client, seeded_user)
    access_payload = decode_access_token(login["access_token"])
    refresh_payload = decode_refresh_token(login["refresh_token"])
    user = db.query(User).filter(User.email == seeded_user["email"]).one()
    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()

    assert user.security_version == 1
    assert access_payload["sv"] == 1
    assert refresh_payload["sv"] == 1
    assert session.organization_id == user.organization_id
    assert session.user_security_version == user.security_version
    assert session.revoked_at is None


def test_stateless_access_token_is_rejected_by_protected_endpoints(
    client,
    seeded_user,
):
    token = create_access_token(
        subject=seeded_user["email"],
        role="owner",
        security_version=1,
    )
    response = client.get(
        "/api/v1/system/status",
        headers=_authorization(token),
    )
    assert response.status_code == 401


def test_jwt_role_claim_is_ignored_and_current_database_role_is_used(
    client,
    seeded_user,
    db,
):
    user = db.query(User).filter(User.email == seeded_user["email"]).one()
    user.role = "viewer"
    db.commit()
    db.refresh(user)

    session_id = new_token_id()
    access_jti = new_token_id()
    stale_claim_token = create_access_token(
        subject=user.email,
        role="owner",
        session_id=session_id,
        jti=access_jti,
        security_version=user.security_version,
    )
    db.add(
        AuthSession(
            id=session_id,
            family_id=new_token_id(),
            user_id=user.id,
            organization_id=user.organization_id,
            user_security_version=user.security_version,
            access_jti=access_jti,
            refresh_jti=new_token_id(),
            refresh_token_hash="a" * 64,
            expires_at=user.updated_at.replace(year=user.updated_at.year + 1),
            ip_address="127.0.0.1",
            user_agent="live-role-test",
        )
    )
    db.commit()

    response = client.get(
        "/api/v1/auth/roles",
        headers=_authorization(stale_claim_token),
    )
    assert response.status_code == 403


def test_role_change_increments_version_and_revokes_existing_sessions(
    client,
    seeded_user,
    db,
):
    login = _login(client, seeded_user)
    user = db.query(User).filter(User.email == seeded_user["email"]).one()
    original_version = user.security_version

    user.role = "viewer"
    db.commit()
    db.expire_all()

    changed_user = db.query(User).filter(User.id == user.id).one()
    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert changed_user.security_version == original_version + 1
    assert changed_user.security_changed_at is not None
    assert session.revoked_at is not None
    assert session.revocation_reason == "user_security_state_changed"

    access = client.get(
        "/api/v1/system/status",
        headers=_authorization(login["access_token"]),
    )
    refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
        headers={"User-Agent": "live-role-test"},
    )
    assert access.status_code == 401
    assert refresh.status_code == 401


def test_password_hash_change_revokes_existing_sessions(
    client,
    seeded_user,
    db,
):
    _login(client, seeded_user)
    user = db.query(User).filter(User.email == seeded_user["email"]).one()
    original_version = user.security_version

    user.hashed_password = hash_password("Replacement@Password123")
    db.commit()
    db.expire_all()

    changed_user = db.query(User).filter(User.id == user.id).one()
    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert changed_user.security_version == original_version + 1
    assert session.revoked_at is not None
    assert session.revocation_reason == "user_security_state_changed"


def test_user_deactivation_revokes_existing_sessions(
    client,
    seeded_user,
    db,
):
    _login(client, seeded_user)
    user = db.query(User).filter(User.email == seeded_user["email"]).one()

    user.is_active = False
    db.commit()
    db.expire_all()

    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert session.revoked_at is not None
    assert session.revocation_reason == "user_security_state_changed"


def test_user_organization_change_revokes_existing_sessions(
    client,
    seeded_user,
    db,
):
    _login(client, seeded_user)
    user = db.query(User).filter(User.email == seeded_user["email"]).one()
    second_org = Organization(
        name="Second Test Org",
        legal_name="Second Test Org",
        country="SA",
        is_active=True,
    )
    db.add(second_org)
    db.commit()

    user.organization_id = second_org.id
    db.commit()
    db.expire_all()

    changed_user = db.query(User).filter(User.id == user.id).one()
    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert changed_user.organization_id == second_org.id
    assert session.revoked_at is not None
    assert session.revocation_reason == "user_security_state_changed"


def test_organization_deactivation_revokes_member_sessions_and_blocks_login(
    client,
    seeded_user,
    db,
):
    login = _login(client, seeded_user)
    user = db.query(User).filter(User.email == seeded_user["email"]).one()
    organization = db.query(Organization).filter(Organization.id == user.organization_id).one()

    organization.is_active = False
    db.commit()
    db.expire_all()

    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert session.revoked_at is not None
    assert session.revocation_reason == "organization_deactivated"

    access = client.get(
        "/api/v1/system/status",
        headers=_authorization(login["access_token"]),
    )
    relogin = client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_user["email"],
            "password": seeded_user["password"],
        },
        headers={"User-Agent": "live-role-test"},
    )
    assert access.status_code == 401
    assert relogin.status_code == 401


def test_change_password_endpoint_revokes_current_and_refresh_tokens(
    client,
    seeded_user,
    db,
):
    login = _login(client, seeded_user)
    response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": seeded_user["password"],
            "new_password": "Changed@Password123",
        },
        headers=_authorization(login["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["sessions_revoked"] is True

    db.expire_all()
    user = db.query(User).filter(User.email == seeded_user["email"]).one()
    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert user.security_version == 2
    assert session.revoked_at is not None
    assert session.revocation_reason == "user_security_state_changed"

    access = client.get(
        "/api/v1/system/status",
        headers=_authorization(login["access_token"]),
    )
    refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
        headers={"User-Agent": "live-role-test"},
    )
    assert access.status_code == 401
    assert refresh.status_code == 401
