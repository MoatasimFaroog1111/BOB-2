"""PostgreSQL-only release assertions not routed through SQLite test fixtures."""

from __future__ import annotations

import json

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.core import Organization, User
from app.models.encrypted_secret import EncryptedSecretVersion
from app.models.tenant_secret import TenantSecretBinding
from app.security.auth import hash_password
from app.services.secret_provider_types import SecretStoreError
from app.services.secret_store import (
    get_tenant_secret,
    put_tenant_secret,
    reset_secret_provider_for_tests,
)


def main() -> None:
    if not settings.DATABASE_URL.startswith("postgresql+"):
        raise SystemExit("PostgreSQL DATABASE_URL is required")
    settings.SECRET_STORE_PROVIDER = "encrypted_db"
    reset_secret_provider_for_tests()

    db = SessionLocal()
    try:
        for org_id, user_id in ((9101, 9111), (9202, 9222)):
            db.add(
                Organization(
                    id=org_id,
                    name=f"PostgreSQL Tenant {org_id}",
                    legal_name=f"PostgreSQL Tenant {org_id}",
                    country="SA",
                    is_active=True,
                )
            )
            db.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=f"owner-{org_id}@example.test",
                    full_name=f"Owner {org_id}",
                    role="owner",
                    hashed_password=hash_password("Postgres@Test123!"),
                    is_active=True,
                )
            )
        db.commit()

        first_value = "postgres-tenant-one-secret-value"
        second_value = "postgres-tenant-two-secret-value"
        put_tenant_secret(
            db,
            organization_id=9101,
            actor_user_id=9111,
            purpose="erp_credentials",
            value=first_value,
        )
        put_tenant_secret(
            db,
            organization_id=9202,
            actor_user_id=9222,
            purpose="erp_credentials",
            value=second_value,
        )
        assert get_tenant_secret(
            db,
            organization_id=9101,
            purpose="erp_credentials",
        ) == first_value
        assert get_tenant_secret(
            db,
            organization_id=9202,
            purpose="erp_credentials",
        ) == second_value

        bindings = db.query(TenantSecretBinding).order_by(TenantSecretBinding.organization_id).all()
        assert [row.organization_id for row in bindings] == [9101, 9202]
        encrypted_rows = db.query(EncryptedSecretVersion).all()
        assert len(encrypted_rows) == 2
        dump = json.dumps(
            [
                {
                    "name": row.secret_name,
                    "version": row.version,
                    "ciphertext": bytes(row.ciphertext).hex(),
                    "tags": row.authenticated_tags,
                }
                for row in encrypted_rows
            ]
        )
        assert first_value not in dump
        assert second_value not in dump

        try:
            put_tenant_secret(
                db,
                organization_id=9202,
                actor_user_id=9111,
                purpose="external_llm_api_key",
                value="must-be-rejected",
            )
        except SecretStoreError as exc:
            assert exc.reason == "secret_store_actor_invalid"
            db.rollback()
        else:
            raise AssertionError("Cross-tenant secret write was accepted")

        print("postgresql-release-check-ok")
    finally:
        db.close()
        reset_secret_provider_for_tests()


if __name__ == "__main__":
    main()
