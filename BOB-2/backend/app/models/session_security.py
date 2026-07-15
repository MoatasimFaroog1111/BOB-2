from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class AuthSessionRotationState(Base, TimestampMixin):
    """Monotonic server-side generation used for atomic refresh rotation."""

    __tablename__ = "auth_session_rotation_states"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_auth_session_rotation_states_session"),
    )

    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("auth_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    family_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthSessionSecurityEvent(Base, TimestampMixin):
    """Append-only, non-secret security history for authentication sessions."""

    __tablename__ = "auth_session_security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    family_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
