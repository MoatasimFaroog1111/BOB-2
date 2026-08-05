"""merge heads: c6f1a8d4e920 and f9c4d1a7b253

The historical migrations landed in two parallel branches because the
P2 cryptographic-bump workflow spun up before the schema-only
``f9c4d1a7b253_add_organization_offboarding`` branch was merged. Both
branches contain correct, additive migrations and Alembic rejects only
because there are two heads.

This merge revision creates a single head so subsequent schema
migrations (P3 ``email_verification_tokens``) can chain linearly.

Revision ID: 7a0c1e8b9d23
Revises: c6f1a8d4e920, f9c4d1a7b253
Create Date: 2026-08-05 14:30:00.000000
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "7a0c1e8b9d23"
down_revision: str | Sequence[str] | None = ("c6f1a8d4e920", "f9c4d1a7b253")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Merge revision: no schema changes, just unifies the two heads.
    pass


def downgrade() -> None:
    # Splitting the merge back into the two parents is a no-op.
    pass