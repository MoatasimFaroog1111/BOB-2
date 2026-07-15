# Explicit tenant selection for historical financial routes

Stage 12 removes the compatibility behavior that silently translated an
`organization_id == 1` predicate into the authenticated tenant.

## Runtime invariant

Every historical financial module now evaluates
`current_organization_id(required=True)` at the database selection or creation
site. Missing request tenant context fails closed. A literal for organization 1
is never reinterpreted as another organization.

SQLAlchemy tenant criteria remain as defense in depth. They can only further
restrict a query; they do not change its intended tenant. Cross-tenant creation,
mutation, and deletion continue to fail before flush.

## Covered modules

- `erp.py`
- `journal_entry_actions.py`
- `chat_journal_lookup.py`
- `bank_posting_v2.py`
- `bank_reconciliation_entry_suggestions.py`
- `bank_reconciliation_hardening.py`

The AST source gate rejects executable comparisons, assignments, or constructor
arguments that hardcode `organization_id` to 1 anywhere under `app/`.

## Scope boundary

This stage changes application source and CI only. It does not prove that the
live backend has deployed the merge commit. Telegram and external LLM execution
remain disabled in production.
