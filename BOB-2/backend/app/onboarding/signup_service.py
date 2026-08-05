"""Self-serve signup orchestration.

The signup service is the public entry point for tenant self-service
acquisition in the ``self_serve_saas`` and ``hybrid_marketplace``
frames. It composes the :class:`TenantProvisioner` and
:class:`EmailVerifier` so the API router stays thin.

The service never sends an email directly — it returns the raw
verification token in the :class:`SignupReceipt` so the caller can
hand it to an email-delivery service. This makes the service fully
testable without an SMTP relay or a third-party email API.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.onboarding.email_verifier import EmailVerifier
from app.onboarding.tenant_provisioner import (
    ProvisionedTenant,
    TenantAlreadyExistsError,
    TenantProvisioner,
    TenantProvisioningError,
)


class SignupError(RuntimeError):
    """Base class for signup failures."""


class SignupAlreadyExistsError(SignupError):
    """The chosen organization slug or owner email is already taken."""


@dataclass(frozen=True)
class SignupReceipt:
    """The result of a successful signup operation.

    ``verification_token`` is the raw token that must be embedded in
    the verification link sent to ``owner_email``. The token is the
    only place it appears in plaintext; storage holds only its HMAC
    digest.
    """

    organization_id: int
    owner_user_id: int
    tenant_slug: str
    owner_email: str
    verification_token: str
    verification_expires_at: datetime


class SignupService:
    """Orchestrate self-serve signup.

    Construct per-request with a DB session. The service is
    intentionally cheap to instantiate: it composes the provisioner
    and verifier but holds no request state itself.
    """

    def __init__(
        self,
        *,
        db: Session,
        email_verifier: EmailVerifier,
        default_org_name: str = "Default Organization",
        default_org_legal_name: str = "Default Organization",
    ) -> None:
        self._db = db
        self._email_verifier = email_verifier
        self._default_org_name = default_org_name
        self._default_org_legal_name = default_org_legal_name

    def signup(
        self,
        *,
        organization_name: str,
        owner_email: str,
        owner_password: str,
        owner_full_name: Optional[str] = None,
        legal_name: Optional[str] = None,
    ) -> SignupReceipt:
        """Run the self-serve signup flow end-to-end.

        Steps:

        1. Provision the tenant atomically (org + owner + RBAC).
        2. Issue an email verification token for the new owner.
        3. Return a receipt that includes the raw verification token.

        On any failure (slug collision, weak password, integrity
        error) the transaction is rolled back and an exception is
        raised. Callers should map
        :class:`TenantAlreadyExistsError` to a 409 response.
        """
        provisioner = TenantProvisioner(
            db=self._db,
            default_org_name=self._default_org_name,
            default_org_legal_name=self._default_org_legal_name,
        )
        try:
            tenant: ProvisionedTenant = provisioner.provision(
                organization_name=organization_name,
                legal_name=legal_name,
                owner_email=owner_email,
                owner_password=owner_password,
                owner_full_name=owner_full_name,
            )
        except TenantAlreadyExistsError as exc:
            raise SignupAlreadyExistsError(str(exc)) from exc
        except TenantProvisioningError:
            raise

        raw_token, expires_at = self._email_verifier.issue(
            user_id=tenant.owner_user_id,
            email=owner_email,
            db=self._db,
        )
        self._db.commit()

        return SignupReceipt(
            organization_id=tenant.organization_id,
            owner_user_id=tenant.owner_user_id,
            tenant_slug=tenant.tenant_slug,
            owner_email=owner_email.lower().strip(),
            verification_token=raw_token,
            verification_expires_at=expires_at,
        )


__all__ = [
    "SignupError",
    "SignupAlreadyExistsError",
    "SignupReceipt",
    "SignupService",
]