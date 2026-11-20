from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Lifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Priority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FaultStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    CONVERTED = "CONVERTED"
    DISMISSED = "DISMISSED"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class NoteKind(StrEnum):
    PROGRESS = "PROGRESS"
    DIAGNOSIS = "DIAGNOSIS"
    REPAIR = "REPAIR"
    TEST = "TEST"


TERMINAL = (OrderStatus.CLOSED, OrderStatus.CANCELLED)


def choice(enum: type[StrEnum], name: str) -> Enum:
    return Enum(enum, name=name, native_enum=False, create_constraint=True)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(160))
    location_id: Mapped[UUID] = mapped_column(ForeignKey("locations.id"), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160))
    serial: Mapped[str | None] = mapped_column(String(160))
    lifecycle: Mapped[Lifecycle] = mapped_column(
        choice(Lifecycle, "asset_lifecycle"), server_default=Lifecycle.ACTIVE
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class FaultReport(Base):
    __tablename__ = "fault_reports"
    __table_args__ = (Index("ix_fault_reports_asset_status", "asset_id", "status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"))
    reporter_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    symptoms: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    suggested_priority: Mapped[Priority] = mapped_column(
        choice(Priority, "suggested_priority")
    )
    reviewed_priority: Mapped[Priority | None] = mapped_column(
        choice(Priority, "reviewed_priority")
    )
    status: Mapped[FaultStatus] = mapped_column(
        choice(FaultStatus, "fault_status"), server_default=FaultStatus.SUBMITTED
    )
    dismissal_reason: Mapped[str | None] = mapped_column(Text)
    related_report_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fault_reports.id")
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(35), unique=True)
    fault_report_id: Mapped[UUID] = mapped_column(
        ForeignKey("fault_reports.id"), unique=True
    )
    priority: Mapped[Priority] = mapped_column(choice(Priority, "work_priority"))
    status: Mapped[OrderStatus] = mapped_column(
        choice(OrderStatus, "work_status"), server_default=OrderStatus.OPEN, index=True
    )
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class AssignmentEvent(Base):
    __tablename__ = "assignment_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    from_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_entity_timestamp", "entity_type", "entity_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[UUID]
    changes: Mapped[dict] = mapped_column(JSONB)
    request_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkNote(Base):
    __tablename__ = "work_notes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[NoteKind] = mapped_column(choice(NoteKind, "work_note_kind"))
    text: Mapped[str] = mapped_column(Text)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_notes.id"), unique=True
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("actor_id", "route", "key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    route: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None]
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    location: Mapped[str | None] = mapped_column(String(256))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
