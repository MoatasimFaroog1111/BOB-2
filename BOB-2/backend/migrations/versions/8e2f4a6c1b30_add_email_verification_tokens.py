"""add email_verification_tokens for self-serve signup

Adds the storage backing for :class:`app.onboarding.email_verifier.EmailVerifier`.

The table stores the HMAC-SHA256 digest of the raw token (never the
raw token), a single-use ``consumed_at`` marker, and the standard
created_at / updated_at timestamps. The unique index on ``token_digest``
is what makes the verifier safe under concurrent signup attempts.

Revision ID: 8e2f4a6c1b30
Revises: 7a0c1e8b9d23
Create Date: 2026-08-05 14:35:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e2f4a6c1b30"
down_revision: str | None = "7a0c1e8b9d23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_verification_tokens",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_email_verification_tokens_digest"),
    )
    for column in ("user_id", "email", "token_digest", "consumed_at"):
        op.create_index(
            f"ix_email_verification_tokens_{column}",
            "email_verification_tokens",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("consumed_at", "token_digest", "email", "user_id"):
        op.drop_index(
            f"ix_email_verification_tokens_{column}",
            table_name="email_verification_tokens",
        )
    op.drop_table("email_verification_tokens")