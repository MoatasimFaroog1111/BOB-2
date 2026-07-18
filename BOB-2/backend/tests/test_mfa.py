from __future__ import annotations

from datetime import timedelta

import pyotp

from app.models.mfa_challenge import MFAChallenge
from app.security.audit_chain import utc_naive


def _activate_mfa(client, auth_headers, seeded_user):
    setup = client.post(
        "/api/v1/auth/mfa/setup",
        json={"current_password": seeded_user["password"]},
        headers=auth_headers,
    )
    assert setup.status_code == 200, setup.text
    totp = pyotp.parse_uri(setup.json()["provisioning_uri"])
    activation = client.post(
        "/api/v1/auth/mfa/activate",
        json={"code": totp.now()},
        headers=auth_headers,
    )
    assert activation.status_code == 200, activation.text
    return totp


def _password_login(client, seeded_user):
    return client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_user["email"],
            "password": seeded_user["password"],
        },
        headers={"User-Agent": "pytest-mfa-device"},
    )


def test_mfa_activation_and_login_issue_session_only_after_code(
    client,
    auth_headers,
    seeded_user,
):
    totp = _activate_mfa(client, auth_headers, seeded_user)
    login = _password_login(client, seeded_user)
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["mfa_required"] is True
    assert body["mfa_token"]
    assert body["access_token"] is None
    assert body["refresh_token"] is None

    next_code = totp.at(totp.timecode(utc_naive()) * totp.interval + totp.interval)
    verified = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": body["mfa_token"], "code": next_code},
        headers={"User-Agent": "pytest-mfa-device"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["access_token"]
    assert verified.json()["refresh_token"]
    assert verified.json()["mfa_required"] is False


def test_mfa_wrong_code_is_rejected(client, auth_headers, seeded_user):
    _activate_mfa(client, auth_headers, seeded_user)
    login = _password_login(client, seeded_user).json()
    response = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": login["mfa_token"], "code": "000000"},
        headers={"User-Agent": "pytest-mfa-device"},
    )
    assert response.status_code == 401


def test_mfa_challenge_is_one_time(client, auth_headers, seeded_user):
    totp = _activate_mfa(client, auth_headers, seeded_user)
    login = _password_login(client, seeded_user).json()
    code = totp.at(totp.timecode(utc_naive()) * totp.interval + totp.interval)
    first = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": login["mfa_token"], "code": code},
        headers={"User-Agent": "pytest-mfa-device"},
    )
    assert first.status_code == 200, first.text
    replay = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": login["mfa_token"], "code": code},
        headers={"User-Agent": "pytest-mfa-device"},
    )
    assert replay.status_code == 401


def test_mfa_challenge_expiry_is_enforced(
    client,
    auth_headers,
    seeded_user,
    db,
):
    totp = _activate_mfa(client, auth_headers, seeded_user)
    login = _password_login(client, seeded_user).json()
    challenge = db.query(MFAChallenge).one()
    challenge.expires_at = utc_naive() - timedelta(seconds=1)
    db.commit()
    code = totp.at(totp.timecode(utc_naive()) * totp.interval + totp.interval)
    response = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": login["mfa_token"], "code": code},
        headers={"User-Agent": "pytest-mfa-device"},
    )
    assert response.status_code == 401


def test_mfa_challenge_is_bound_to_device(client, auth_headers, seeded_user):
    totp = _activate_mfa(client, auth_headers, seeded_user)
    login = _password_login(client, seeded_user).json()
    code = totp.at(totp.timecode(utc_naive()) * totp.interval + totp.interval)
    response = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": login["mfa_token"], "code": code},
        headers={"User-Agent": "different-device"},
    )
    assert response.status_code == 401
