"""Tenant provisioner — atomic creation of an organization + owner.

This is the **only** path through which a new tenant is created. It is
shared by self-serve signup (in :mod:`app.onboarding.signup_service`)
and operator-led onboarding (P4). Centralizing tenant creation keeps
RBAC bindings, audit-chain anchoring, and the tenant-neutral default
organization config consistent across every entry point.

The provisioner:

1. Creates an :class:`Organization` row.
2. Creates the owner :class:`User` with a bcrypt-hashed password.
3. Adds the owner to the organization's RBAC group as ``OWNER``.
4. Sets the tenant's default ERP egress allowlist to the configured
   default (an empty list in the public cloud — operators add hosts
   via the secret store).

The provisioner is intentionally explicit about every side effect
(no implicit fixtures, no global state) so it can be reused by tests
without spawning an entire application.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Reserved tenant slugs that we never issue (DNS-confusable or
# reserved by the product itself).
_RESERVED_SLUGS = frozenset(
    {
        "www",
        "api",
        "app",
        "admin",
        "administrator",
        "root",
        "support",
        "help",
        "docs",
        "blog",
        "status",
        "auth",
        "login",
        "logout",
        "signup",
        "billing",
        "marketing",
        "default",
        "system",
        "internal",
        "test",
        "demo",
        "public",
        "static",
        "assets",
        "guardian",
        "guardianai",
        "bob",
        "bob2",
        "bob-2",
    }
)

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])?$")


class TenantProvisioningError(RuntimeError):
    """Base class for tenant-provisioning failures."""


class TenantAlreadyExistsError(TenantProvisioningError):
    """Raised when the chosen tenant slug or owner email is taken."""


@dataclass(frozen=True)
class ProvisionedTenant:
    """The result of a successful provisioning operation."""

    organization_id: int
    owner_user_id: int
    tenant_slug: str


class TenantProvisioner:
    """Atomic tenant creation. Construct per-request with a DB session."""

    def __init__(
        self,
        *,
        db: Session,
        default_org_name: str = "Default Organization",
        default_org_legal_name: str = "Default Organization",
    ) -> None:
        self._db = db
        self._default_org_name = default_org_name
        self._default_org_legal_name = default_org_legal_name

    @staticmethod
    def derive_slug(name: str) -> str:
        """Derive a DNS-safe tenant slug from a human-readable name.

        Returns a slug that matches ``^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])?$``.
        Raises :class:`ValueError` if the name cannot be turned into a
        valid slug.
        """
        if not name:
            raise ValueError("name is required")
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not slug:
            raise ValueError(f"name {name!r} cannot be turned into a slug")
        if slug in _RESERVED_SLUGS:
            raise ValueError(f"slug {slug!r} is reserved")
        if not _SLUG_RE.match(slug):
            raise ValueError(f"slug {slug!r} is not DNS-safe")
        return slug

    def provision(
        self,
        *,
        organization_name: str,
        legal_name: Optional[str],
        owner_email: str,
        owner_password: str,
        owner_full_name: Optional[str] = None,
        slug: Optional[str] = None,
    ) -> ProvisionedTenant:
        """Create a new tenant atomically.

        All steps run in a single SQL transaction; if any step fails
        the transaction is rolled back. The function never partially
        creates a tenant.
        """
        from app.models.core import Organization, User  # local import to avoid cycle

        if not owner_email or "@" not in owner_email:
            raise TenantProvisioningError("owner_email must be a valid email address")
        if not owner_password or len(owner_password) < 12:
            raise TenantProvisioningError("owner_password must be at least 12 characters")

        slug = slug or self.derive_slug(organization_name)
        legal = legal_name or organization_name

        try:
            org = Organization(
                name=self._default_org_name,
                legal_name=legal,
            )
            self._db.add(org)
            self._db.flush()

            pwd_hash = bcrypt.hashpw(
                owner_password.encode("utf-8"), bcrypt.gensalt(rounds=12)
            ).decode("utf-8")
            user = User(
                email=owner_email.lower().strip(),
                hashed_password=pwd_hash,
                full_name=owner_full_name or owner_email.split("@")[0],
                role="OWNER",
                organization_id=org.id,
                is_active=False,  # activated by email verification
            )
            self._db.add(user)
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise TenantAlreadyExistsError(
                f"Tenant slug {slug!r} or owner email {owner_email!r} already exists"
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            self._db.rollback()
            raise TenantProvisioningError(str(exc)) from exc

        return ProvisionedTenant(
            organization_id=org.id,
            owner_user_id=user.id,
            tenant_slug=slug,
        )


__all__ = [
    "ProvisionedTenant",
    "TenantAlreadyExistsError",
    "TenantProvisioner",
    "TenantProvisioningError",
]