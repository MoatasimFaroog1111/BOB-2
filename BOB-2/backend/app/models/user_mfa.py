from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class UserMFASetting(Base, TimestampMixin):
    __tablename__ = "user_mfa_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_mfa_settings_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    secret_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    last_accepted_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
