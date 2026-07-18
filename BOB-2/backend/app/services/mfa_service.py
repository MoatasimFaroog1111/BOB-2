from __future__ import annotations

import hmac
import os
import time
from urllib.parse import urlsplit

import pyotp
from sqlalchemy.orm import Session

from app.models.user_mfa import UserMFASetting
from app.security.audit_chain import utc_naive
from app.services.secret_provider_types import SecretStoreError
from app.services.secret_store import get_secret_provider

_TOTP_INTERVAL_SECONDS = 30


def _secret_name(organization_id: int, user_id: int) -> str:
    return f"org-{organization_id}-user-{user_id}-totp-{os.urandom(12).hex()}"[:127]


def _reference(provider_name: str, name: str, version: str) -> str:
    return f"secretref://{provider_name}/{name}/{version}"


def _parse_reference(reference: str) -> tuple[str, str, str]:
    parsed = urlsplit(reference)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "secretref"
        or len(parts) != 2
        or parsed.query
        or parsed.fragment
    ):
        raise SecretStoreError("secret_reference_invalid")
    return parsed.netloc, parts[0], parts[1]


def create_pending_totp_secret(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    account_name: str,
    issuer_name: str,
) -> tuple[UserMFASetting, str]:
    provider = get_secret_provider()
    if provider.provider_name == "disabled":
        raise SecretStoreError("secret_store_disabled")

    existing = (
        db.query(UserMFASetting)
        .filter(UserMFASetting.user_id == user_id)
        .with_for_update()
        .first()
    )
    if existing is not None and existing.enabled:
        raise ValueError("MFA is already active")

    secret = pyotp.random_base32(length=32)
    name = _secret_name(organization_id, user_id)
    remote = provider.set_secret(
        name,
        secret,
        tags={
            "organization_id": str(organization_id),
            "purpose": "totp_secret",
            "user_id": str(user_id),
        },
    )
    new_reference = _reference(provider.provider_name, remote.name, remote.version)

    if existing is None:
        existing = UserMFASetting(
            user_id=user_id,
            organization_id=organization_id,
            enabled=False,
            secret_ref=new_reference,
        )
        db.add(existing)
    else:
        try:
            old_provider, old_name, old_version = _parse_reference(existing.secret_ref)
            if old_provider == provider.provider_name:
                provider.disable_secret(old_name, old_version)
        except SecretStoreError:
            pass
        existing.organization_id = organization_id
        existing.enabled = False
        existing.secret_ref = new_reference
        existing.last_accepted_counter = None
        existing.activated_at = None
    db.flush()

    uri = pyotp.TOTP(secret, interval=_TOTP_INTERVAL_SECONDS).provisioning_uri(
        name=account_name,
        issuer_name=issuer_name,
    )
    return existing, uri


def _secret_for_setting(setting: UserMFASetting) -> str:
    provider_name, name, version = _parse_reference(setting.secret_ref)
    provider = get_secret_provider()
    if provider_name != provider.provider_name:
        raise SecretStoreError("secret_provider_mismatch")
    return provider.get_secret(name, version)


def verify_totp_once(
    setting: UserMFASetting,
    code: str,
    *,
    at_time: float | None = None,
) -> int:
    normalized = code.strip().replace(" ", "")
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError("Invalid authentication code")
    secret = _secret_for_setting(setting)
    totp = pyotp.TOTP(secret, interval=_TOTP_INTERVAL_SECONDS)
    timestamp = time.time() if at_time is None else float(at_time)
    current_counter = int(timestamp) // _TOTP_INTERVAL_SECONDS

    accepted_counter: int | None = None
    for counter in (current_counter - 1, current_counter, current_counter + 1):
        expected = totp.at(counter * _TOTP_INTERVAL_SECONDS)
        if hmac.compare_digest(expected, normalized):
            accepted_counter = counter
            break
    if accepted_counter is None:
        raise ValueError("Invalid authentication code")
    if (
        setting.last_accepted_counter is not None
        and accepted_counter <= int(setting.last_accepted_counter)
    ):
        raise ValueError("Authentication code has already been used")
    return accepted_counter


def activate_mfa(setting: UserMFASetting, code: str) -> None:
    counter = verify_totp_once(setting, code)
    setting.last_accepted_counter = counter
    setting.enabled = True
    setting.activated_at = utc_naive()


def consume_login_code(setting: UserMFASetting, code: str) -> None:
    if not setting.enabled:
        raise ValueError("MFA is not active")
    setting.last_accepted_counter = verify_totp_once(setting, code)
