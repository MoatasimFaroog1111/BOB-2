"""Fail CI when authorization regresses to stale JWT roles or stateless sessions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"Live-role session control failed: {name}")
    print(f"OK: {name}")


def main() -> None:
    dependencies = source("app/security/dependencies.py")
    token_security = source("app/security/auth.py")
    auth_api = source("app/api/v1/auth.py")
    models = source("app/models/core.py")
    migration = source(
        "migrations/versions/f3a9d2c7b410_add_live_role_session_security.py"
    )

    require(
        "protected endpoints require a server session",
        "if not isinstance(session_id, str)" in dependencies
        and "return payload" not in dependencies.split(
            "if not isinstance(session_id, str)", 1
        )[1].split("auth_session =", 1)[0],
    )
    require(
        "JWT role is overwritten from the database",
        'payload["role"] = user.role' in dependencies,
    )
    require(
        "authorization checks session security version",
        "auth_session.user_security_version != current_security_version"
        in dependencies,
    )
    require(
        "authorization checks token security version",
        "token_security_version != current_security_version" in dependencies,
    )
    require(
        "authorization checks live organization status",
        "not organization or not organization.is_active" in dependencies,
    )
    require(
        "permission gate receives live role payload",
        "role_has_permission(payload.get(\"role\"), permission)" in dependencies,
    )

    require(
        "access tokens support security version binding",
        "security_version: int | None = None" in token_security
        and 'payload["sv"] = int(security_version)' in token_security,
    )
    require(
        "role claim is explicitly non-authoritative",
        "role claim is retained for client compatibility only" in token_security,
    )

    require(
        "login snapshots organization and security version",
        "organization_id=organization.id" in auth_api
        and "user_security_version=security_version" in auth_api,
    )
    require(
        "refresh validates current security state",
        "auth_session.user_security_version != current_security_version"
        in auth_api,
    )
    require(
        "password change uses server-side invalidation path",
        '@router.post("/change-password"' in auth_api
        and "user.hashed_password = hash_password(payload.new_password)" in auth_api,
    )

    for field_name in (
        '"role"',
        '"hashed_password"',
        '"is_active"',
        '"organization_id"',
        '"email"',
    ):
        require(
            f"user security change tracks {field_name}",
            field_name in models.split("_USER_SECURITY_FIELDS", 1)[1],
        )
    require(
        "user changes increment security version",
        "target.security_version = int(target.security_version or 1) + 1"
        in models,
    )
    require(
        "user changes revoke sessions in the same transaction",
        'revocation_reason="user_security_state_changed"' in models,
    )
    require(
        "organization deactivation revokes member sessions",
        'revocation_reason="organization_deactivated"' in models,
    )

    require(
        "migration invalidates pre-version sessions",
        "security_version_migration" in migration,
    )
    require(
        "migration tenant-binds auth sessions",
        '"organization_id"' in migration
        and '"user_security_version"' in migration,
    )


if __name__ == "__main__":
    main()
