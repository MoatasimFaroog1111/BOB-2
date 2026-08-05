"""Onboarding module — self-serve signup, email verification, tenant provisioning.

Exposes:

- :class:`app.onboarding.signup_service.SignupService` — orchestrates
  the self-serve signup flow: create pending user + organization,
  issue email verification token, return signup receipt.
- :class:`app.onboarding.email_verifier.EmailVerifier` — issues and
  verifies single-use, +24h-TTL email verification tokens. Tokens are
  stored hashed (HMAC-SHA256 of the raw token) so a database leak
  does not enable account takeover.
- :class:`app.onboarding.tenant_provisioner.TenantProvisioner` —
  atomic provisioning of an organization, an owner user, and the
  minimum RBAC bindings for first login. The provisioner is the only
  place where a new tenant is constructed; it is shared by self-serve
  signup and operator-led onboarding.

The module is intentionally pure-Python: it takes the database session
and the password hasher as dependencies, so it can be tested without
running the FastAPI app.
"""
from app.onboarding.email_verifier import EmailVerifier, EmailVerificationError
from app.onboarding.signup_service import (
    SignupAlreadyExistsError,
    SignupError,
    SignupReceipt,
    SignupService,
)
from app.onboarding.tenant_provisioner import (
    TenantAlreadyExistsError,
    TenantProvisioner,
    TenantProvisioningError,
)

__all__ = [
    "EmailVerifier",
    "EmailVerificationError",
    "SignupAlreadyExistsError",
    "SignupError",
    "SignupReceipt",
    "SignupService",
    "TenantAlreadyExistsError",
    "TenantProvisioner",
    "TenantProvisioningError",
]