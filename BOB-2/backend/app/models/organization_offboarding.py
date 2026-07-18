from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin


class OrganizationOffboardingCase(Base, TimestampMixin):
    __tablename__ = "organization_offboarding_cases"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            name="uq_organization_offboarding_cases_organization_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="retention_hold",
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    retention_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_disabled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deletion_authorized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
