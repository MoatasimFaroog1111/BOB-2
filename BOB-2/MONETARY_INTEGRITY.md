# Fixed-Point Monetary Integrity

## Application standard

GuardianAI accounting amounts use `decimal.Decimal` in application code and `NUMERIC(20,2)` in persisted monetary columns.

- scale: two fractional digits
- rounding rule for imported values: `ROUND_HALF_UP`
- maximum absolute value: `999999999999999999.99`
- non-finite values such as NaN and Infinity: rejected
- journal debit and credit values: non-negative
- each journal line: exactly one positive debit or credit
- journal total: positive and exactly balanced at two-decimal scale

Confidence scores, vector embeddings, geometric PDF coordinates, percentages, and similarity scores are not monetary values and may remain floating point.

## JSON and audit records

Durable journal JSON, Telegram approval payloads, audit metadata, hashes, and idempotency inputs use fixed-scale strings such as `"64083.75"`. This prevents a JSON encoder from changing the accounting representation.

Bank-reconciliation report JSON is persisted through `FixedPointJSON`, which recursively converts `Decimal` values to fixed-scale strings before database serialization.

## Odoo boundary

Odoo XML-RPC does not support Python `Decimal`. GuardianAI therefore validates and balances all values as `Decimal`, creates a canonical two-decimal string, converts that string to `float` only in the final XML-RPC payload, and verifies that converting the boundary value back still produces the exact application amount.

No monetary totals, comparisons, hashes, or balance decisions use that boundary float.

## Database migration

Alembic revision `e6b8c1d4a290` converts:

- `journal_entries.total_debit`
- `journal_entries.total_credit`
- `bank_reconciliation_audit_logs.statement_total`
- `bank_reconciliation_audit_logs.ledger_total`
- `bank_reconciliation_audit_logs.difference`

to `NUMERIC(20,2)`.

Before conversion, existing journal totals are normalized to two decimals and checked. The migration fails closed if an existing entry would be non-positive or unbalanced after normalization. It does not silently repair an accounting imbalance.

The journal table also receives database constraints requiring positive and equal debit and credit totals.

## Deployment gate

Before applying the migration to a live database:

1. Take and verify a restorable database backup.
2. Run a read-only query identifying entries whose two-decimal debit and credit totals differ.
3. Investigate and approve any accounting correction separately; do not bypass the migration check.
4. Apply `alembic upgrade head` in a controlled release.
5. Verify the Alembic revision is `e6b8c1d4a290` and inspect the resulting numeric column definitions.
6. Run a balanced draft-entry smoke test using fractional values such as 0.10, 0.20, and 0.30.

Merging this code does not prove the migration was applied to a live backend database.
