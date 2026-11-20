from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, ConfigDict, Field

from app.db.repairs import Decision
from app.db.workflow import NoteKind, OrderStatus, Priority
from app.schemas.workflow import (
    Code,
    Label,
    Note,
    OrderRead,
    Read,
    UtcTime,
    Versioned,
    Write,
)


class NoteFields(Write):
    kind: NoteKind
    text: Note


class LabourFields(Write):
    minutes: int = Field(strict=True, gt=0, le=2_147_483_647)
    work_date: date
    description: Note


class PartFields(Write):
    part_code: Code
    description: Note
    quantity: Annotated[
        Decimal,
        Field(gt=0, max_digits=14, decimal_places=4, allow_inf_nan=False),
        AfterValidator(lambda value: value.normalize()),
    ]
    unit: Code


class AddNote(NoteFields, Versioned):
    pass


class AddLabour(LabourFields, Versioned):
    pass


class AddPart(PartFields, Versioned):
    pass


class SubmitRepair(Versioned):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "expected_version": 6,
                    "diagnosis": "Fictional bearing wear recorded during inspection",
                    "repair_summary": "Replacement bearing recorded",
                    "test_results": "Fictional test results recorded",
                    "external_reference": "DEMO-WORK-REF",
                }
            ]
        }
    )

    diagnosis: Note
    repair_summary: Note
    test_results: Note
    external_reference: Label | None = None


class VerifyRepair(Versioned):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "expected_version": 7,
                    "decision": "ACCEPT",
                    "notes": "Reviewed the repair evidence",
                },
                {
                    "expected_version": 7,
                    "decision": "REJECT",
                    "notes": "Repeat and document the test",
                },
            ]
        }
    )

    decision: Decision
    notes: Note


class CorrectionFields(Versioned):
    entry_id: UUID
    reason: Note


class NoteCorrection(CorrectionFields):
    entry_type: Literal["note"]
    replacement: NoteFields


class LabourCorrection(CorrectionFields):
    entry_type: Literal["labour"]
    replacement: LabourFields


class PartCorrection(CorrectionFields):
    entry_type: Literal["part"]
    replacement: PartFields


Correction = Annotated[
    NoteCorrection | LabourCorrection | PartCorrection,
    Field(discriminator="entry_type"),
]


class HistoryEvent(Read):
    id: UUID
    resource_id: UUID
    entity_type: str
    action: str
    actor_id: UUID
    created_at: UtcTime
    details: dict
    request_id: UUID | None


class PartTotal(Read):
    part_code: str
    unit: str
    quantity: Decimal


class RepairTotals(Read):
    labour_minutes: int
    parts: list[PartTotal]


class OrderDetail(OrderRead):
    totals: RepairTotals


class MaintenanceSummary(Read):
    by_status: dict[OrderStatus, int]
    by_priority: dict[Priority, int]
    overdue_count: int
    average_closure_seconds: float | None
