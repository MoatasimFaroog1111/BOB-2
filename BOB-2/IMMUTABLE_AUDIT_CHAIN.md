# Immutable tamper-evident audit chain

Stage 13 makes the central `audit_logs` table append-only and chains events per
organization.

## Write boundary

Every ORM `AuditLog` insert is sealed in the same database transaction. The
application derives the scope from `organization_id`, serializes writers for the
scope, allocates a monotonic sequence number, links the prior hash, and computes
a canonical SHA-256 event hash. Client-supplied chain fields are overwritten.

PostgreSQL uses a transaction-scoped advisory lock for each chain. SQLite keeps
the same deterministic behavior for tests and local development. Each tenant
has an independent chain; events with no tenant use the `system` chain.

## Immutability

Application-level flush guards reject ORM updates and deletes. Database triggers
reject direct SQL `UPDATE` and `DELETE`, so ordinary application/database roles
can only append. Unique scope/sequence and event-hash constraints prevent silent
duplication.

Migration `b4e2c7d9f130` deterministically backfills every historical audit row,
creates the current chain heads, then activates the mutation triggers.

## Verification

Authorized users with `view_audit_logs` may call:

`GET /api/v1/system/audit-integrity`

The response contains chain validity, event count, last sequence/hash, and a
safe failure code. It does not return event details. Verification recalculates
every event hash and checks sequence continuity, previous-hash links, and the
stored chain head.

## Trust boundary

This is database-enforced append-only storage and tamper evidence. It is not a
WORM archive against a PostgreSQL superuser who can disable triggers and rewrite
the complete chain and head. Production audit evidence should additionally be
exported or checkpointed to independently controlled append-only/WORM storage.
Telegram and external LLM execution remain disabled in production.
