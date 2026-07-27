from urllib.parse import parse_qs, urlsplit

from app.api.v1 import account_access


def _token_from_url(url: str, name: str) -> str:
    token = parse_qs(urlsplit(url).query).get(name, [""])[0]
    assert token
    return token


def test_password_reset_request_is_generic_for_unknown_account(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        account_access,
        "_send_password_reset_email",
        lambda recipient, reset_url: sent.append((recipient, reset_url)) or True,
    )

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )

    assert response.status_code == 202
    assert "إذا كان البريد" in response.json()["message"]
    assert sent == []


def test_password_reset_changes_password_and_revokes_token(client, seeded_user, monkeypatch):
    sent = []
    monkeypatch.setattr(
        account_access,
        "_send_password_reset_email",
        lambda recipient, reset_url: sent.append((recipient, reset_url)) or True,
    )

    request_response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": seeded_user["email"]},
    )
    assert request_response.status_code == 202
    assert len(sent) == 1
    token = _token_from_url(sent[0][1], "reset_token")

    new_password = "New@TestPass5678!"
    confirm_response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": new_password},
    )
    assert confirm_response.status_code == 200, confirm_response.text

    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_user["email"], "password": seeded_user["password"]},
        headers={"User-Agent": "password-reset-old-password"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": seeded_user["email"], "password": new_password},
        headers={"User-Agent": "password-reset-new-password"},
    )
    assert new_login.status_code == 200, new_login.text

    replay = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "Another@TestPass9012!"},
    )
    assert replay.status_code == 400


def test_owner_can_invite_and_invited_user_can_register(
    client,
    auth_headers,
    monkeypatch,
):
    monkeypatch.setattr(
        account_access,
        "_send_invitation_email",
        lambda recipient, invite_url, role: False,
    )

    invitation = client.post(
        "/api/v1/auth/invitations",
        json={"email": "new.accountant@example.com", "role": "accountant"},
        headers=auth_headers,
    )
    assert invitation.status_code == 201, invitation.text
    invitation_data = invitation.json()
    assert invitation_data["email_sent"] is False
    token = _token_from_url(invitation_data["invite_url"], "invite")

    password = "Invite@TestPass1234!"
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "invite_token": token,
            "email": "new.accountant@example.com",
            "full_name": "New Accountant",
            "password": password,
        },
    )
    assert registration.status_code == 201, registration.text

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "new.accountant@example.com", "password": password},
        headers={"User-Agent": "invited-account-login"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "accountant"

    replay = client.post(
        "/api/v1/auth/register",
        json={
            "invite_token": token,
            "email": "new.accountant@example.com",
            "full_name": "New Accountant",
            "password": password,
        },
    )
    assert replay.status_code == 409


def test_owner_role_cannot_be_invited(client, auth_headers):
    response = client.post(
        "/api/v1/auth/invitations",
        json={"email": "second.owner@example.com", "role": "owner"},
        headers=auth_headers,
    )
    assert response.status_code == 400
