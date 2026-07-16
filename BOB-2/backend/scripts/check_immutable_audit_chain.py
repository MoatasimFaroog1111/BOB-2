"""Static guard for immutable audit-chain controls."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


core = source("app/models/core.py")
chain = source("app/security/audit_chain.py")
integrity = source("app/services/audit_integrity.py")
system = source("app/api/v1/system.py")
migration = source("migrations/versions/b4e2c7d9f130_add_immutable_audit_chain.py")
tests = source("tests/test_immutable_audit_chain.py")

for marker in (
    "class AuditLogChainHead",
    "scope_key",
    "sequence_number",
    "previous_hash",
    "event_hash",
    "event_version",
    "@event.listens_for(Session, "before_flush")",
    "AuditLogMutationError",
    "pg_advisory_xact_lock",
    "trg_audit_logs_no_update",
    "trg_audit_logs_no_delete",
):
    require(marker in core, f"Audit model control missing: {marker}")

for marker in (
    "canonical_json",
    "compute_audit_event_hash",
    "verify_audit_rows",
    "GENESIS_HASH",
):
    require(marker in chain, f"Audit hashing control missing: {marker}")

require("verify_tenant_audit_chain" in integrity, "Tenant audit verifier missing")
require('@router.get("/audit-integrity")' in system, "Audit-integrity endpoint missing")
require('require_permission("view_audit_logs")' in system, "Audit-integrity endpoint permission missing")
require('revision = "b4e2c7d9f130"' in migration, "Audit migration revision changed")
require('down_revision = "a8c4e1f2d670"' in migration, "Audit migration parent changed")
require("UPDATE audit_logs" in migration and "DELETE ON audit_logs" in migration, "Append-only migration triggers missing")
for marker in (
    "test_database_triggers_block_direct_update_and_delete",
    "test_verifier_detects_out_of_band_chain_corruption",
    "test_integrity_endpoint_is_permission_and_tenant_scoped",
):
    require(marker in tests, f"Audit regression missing: {marker}")

print("Immutable audit-chain source guard passed.")
