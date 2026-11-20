from datetime import UTC, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.db.workflow import FaultStatus, Lifecycle, OrderStatus, Priority

Code = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
Note = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]


def parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError("Use an ISO 8601 timestamp with an offset")


UtcTime = Annotated[
    AwareDatetime,
    BeforeValidator(parse_datetime),
    AfterValidator(lambda value: value.astimezone(UTC)),
]


class Write(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def reject_null_bytes(self) -> Self:
        if any(
            isinstance(value, str) and "\x00" in value
            for value in self.__dict__.values()
        ):
            raise ValueError("Text must not contain null characters")
        return self


class Versioned(Write):
    expected_version: int = Field(strict=True, ge=1)


class Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    page: int
    page_size: int
    total: int


class LocationCreate(Write):
    code: Code
    name: Label
    description: Note | None = None


class LocationRead(Read):
    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    version: int


class LocationPatch(Versioned):
    code: Code | None = None
    name: Label | None = None
    description: Note | None = None
    is_active: bool | None = None


class AssetCreate(Write):
    asset_code: Code
    name: Label
    category: Label
    location_id: UUID
    manufacturer: Label | None = None
    model: Label | None = None
    serial: Label | None = None


class AssetRead(Read):
    id: UUID
    asset_code: str
    name: str
    category: str
    location_id: UUID
    manufacturer: str | None
    model: str | None
    serial: str | None
    lifecycle: Lifecycle
    version: int


class AssetPatch(Versioned):
    asset_code: Code | None = None
    name: Label | None = None
    category: Label | None = None
    location_id: UUID | None = None
    manufacturer: Label | None = None
    model: Label | None = None
    serial: Label | None = None
    lifecycle: Lifecycle | None = None


class FaultCreate(Write):
    asset_id: UUID
    title: Label
    symptoms: Note
    observed_at: UtcTime
    suggested_priority: Priority


class OrderSummary(Read):
    id: UUID
    order_number: str
    priority: Priority
    status: OrderStatus


class FaultRead(Read):
    id: UUID
    asset_id: UUID
    reporter_id: UUID
    title: str
    symptoms: str
    observed_at: UtcTime
    suggested_priority: Priority
    reviewed_priority: Priority | None
    status: FaultStatus
    dismissal_reason: str | None
    related_report_id: UUID | None
    version: int
    work_order: OrderSummary | None = None


class Dismiss(Versioned):
    reason: Note
    related_report_id: UUID | None = None


class Convert(Versioned):
    priority: Priority
    review_notes: Note | None = None


class OrderRead(OrderSummary):
    fault_report_id: UUID
    assigned_to: UUID | None
    due_at: UtcTime | None
    started_at: UtcTime | None
    submitted_at: UtcTime | None
    closed_at: UtcTime | None
    version: int


class Assignment(Versioned):
    technician_id: UUID
    due_at: UtcTime
    reason: Note


class WorkNote(Versioned):
    note: Note


class Pause(Versioned):
    reason: Note


class Cancel(Versioned):
    reason: Note
    handover_note: Note | None = None
