from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base
from app.db.workflow import choice


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class LabourEntry(Base):
    __tablename__ = "labour_entries"
    __table_args__ = (CheckConstraint("minutes > 0", name="labour_positive_minutes"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    technician_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    minutes: Mapped[int]
    work_date: Mapped[date]
    description: Mapped[str] = mapped_column(Text)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("labour_entries.id"), unique=True
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PartUsage(Base):
    __tablename__ = "part_usage"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0 AND quantity < 'Infinity'::numeric",
            name="parts_positive_quantity",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    technician_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    part_code: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    unit: Mapped[str] = mapped_column(String(64))
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("part_usage.id"), unique=True
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RepairSubmission(Base):
    __tablename__ = "repair_submissions"
    __table_args__ = (
        UniqueConstraint(
            "order_id", "order_version", name="uq_submission_order_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    technician_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    order_version: Mapped[int]
    diagnosis: Mapped[str] = mapped_column(Text)
    repair_summary: Mapped[str] = mapped_column(Text)
    test_results: Mapped[str] = mapped_column(Text)
    external_reference: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("repair_submissions.id"), unique=True
    )
    verifier_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[Decision] = mapped_column(
        choice(Decision, "verification_decision")
    )
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
