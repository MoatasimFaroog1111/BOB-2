"""Fail CI if refresh rotation regresses to a non-atomic or non-audited flow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"Atomic refresh control failed: {name}")
    print(f"OK: {name}")


def main() -> None:
    auth_api = read("app/api/v1/auth.py")
    session_issuer = read("app/services/auth_session_issuer.py")
    auth_flow = auth_api + "\n" + session_issuer
    token_code = read("app/security/auth.py")
    service = read("app/services/refresh_token_rotation.py")
    models = read("app/models/session_security.py")
    migration = read("migrations/versions/a8c4e1f2d670_add_atomic_refresh_rotation.py")

    require("login refresh token starts at generation zero", "rotation_generation=0" in auth_flow)
    require("refresh token carries signed generation", 'payload["rgn"] = int(rotation_generation)' in token_code)
    require("refresh endpoint requires generation", 'token_data.get("rgn")' in auth_api)
    require("rotation row is locked when supported", ".with_for_update()" in auth_api and ".with_for_update()" in service)
    require("compare-and-swap generation claim", "claim_refresh_generation(" in auth_api)
    require("CAS predicates include expected generation", "AuthSessionRotationState.generation == expected_generation" in service)
    require("CAS checks exactly one winner", "return result.rowcount == 1" in service)
    require("concurrent loser revokes token family", 'reason="concurrent_refresh_replay"' in auth_api)
    require("old token replay revokes token family", 'event_type="refresh_replay_detected"' in auth_api)
    require("successful rotation is audited", 'event_type="refresh_rotated"' in auth_api)
    require("session creation is audited", 'event_type="session_created"' in auth_flow)
    require("security events do not store token material", "refresh_token_hash" not in models and "refresh_jti" not in models)
    require("event metadata removes sensitive keys", "_FORBIDDEN_EVENT_KEYS" in service and '"token"' in service and '"password"' in service)
    require("migration invalidates pre-generation sessions", "atomic_rotation_migration" in migration)
    require("migration creates rotation state", "auth_session_rotation_states" in migration)
    require("migration creates security events", "auth_session_security_events" in migration)


if __name__ == "__main__":
    main()
