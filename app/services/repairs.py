from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.repairs import (
    Decision,
    LabourEntry,
    PartUsage,
    RepairSubmission,
    Verification,
)
from app.db.workflow import AssignmentEvent, OrderStatus, WorkNote, WorkOrder
from app.schemas.repairs import CorrectionFields, SubmitRepair, VerifyRepair
from app.schemas.workflow import Write
from app.services.commands import conflict, not_found
from app.services.workflow import transition

RECORDS = {
    "note": (WorkNote, "author_id"),
    "labour": (LabourEntry, "technician_id"),
    "part": (PartUsage, "technician_id"),
}


def append_record(
    session: Session,
    order: WorkOrder,
    actor_id: UUID,
    entry_type: str,
    data: Write,
    *,
    supersedes_id: UUID | None = None,
    correction_reason: str | None = None,
) -> dict:
    transition(
        order, (OrderStatus.IN_PROGRESS, OrderStatus.AWAITING_PARTS), order.status
    )
    model, author = RECORDS[entry_type]
    entry_id = uuid4()
    session.add(
        model(
            id=entry_id,
            order_id=order.id,
            supersedes_id=supersedes_id,
            correction_reason=correction_reason,
            **{author: actor_id},
            **data.model_dump(exclude={"expected_version"}),
        )
    )
    return {"entry_id": str(entry_id), "entry_type": entry_type}


def correct_record(
    session: Session, order: WorkOrder, actor_id: UUID, data: CorrectionFields
) -> dict:
    model, author = RECORDS[data.entry_type]
    original = session.get(model, data.entry_id)
    if (
        original is None
        or original.order_id != order.id
        or getattr(original, author) != actor_id
    ):
        raise not_found()
    if (
        session.scalar(select(model.id).where(model.supersedes_id == original.id))
        is not None
    ):
        raise conflict("ENTRY_SUPERSEDED", "Correct the current replacement entry")
    return append_record(
        session,
        order,
        actor_id,
        data.entry_type,
        data.replacement,
        supersedes_id=original.id,
        correction_reason=data.reason,
    )


def submit_repair(
    session: Session, order: WorkOrder, actor_id: UUID, data: SubmitRepair
) -> dict:
    transition(order, (OrderStatus.IN_PROGRESS,), OrderStatus.AWAITING_VERIFICATION)
    order.submitted_at = datetime.now(UTC)
    submission = RepairSubmission(
        id=uuid4(),
        order_id=order.id,
        technician_id=actor_id,
        order_version=order.version,
        **data.model_dump(exclude={"expected_version"}),
    )
    session.add(submission)
    return {"submission_id": str(submission.id)}


def verify_repair(
    session: Session, order: WorkOrder, actor_id: UUID, data: VerifyRepair
) -> dict:
    if order.status != OrderStatus.AWAITING_VERIFICATION:
        raise conflict("INVALID_TRANSITION", "Order is not awaiting verification")

    submission = session.scalar(
        select(RepairSubmission).where(
            RepairSubmission.order_id == order.id,
            RepairSubmission.order_version == order.version,
        )
    )
    previously_assigned = (
        select(AssignmentEvent.id)
        .where(
            AssignmentEvent.order_id == order.id, AssignmentEvent.to_user_id == actor_id
        )
        .exists()
    )
    if actor_id == submission.technician_id or session.scalar(
        select(previously_assigned)
    ):
        raise ApiError(
            403, "SELF_VERIFICATION", "A repair participant cannot verify this order"
        )

    accepted = data.decision == Decision.ACCEPT
    transition(
        order,
        (OrderStatus.AWAITING_VERIFICATION,),
        OrderStatus.CLOSED if accepted else OrderStatus.IN_PROGRESS,
    )
    if accepted:
        order.closed_at = datetime.now(UTC)
    verification = Verification(
        id=uuid4(),
        order_id=order.id,
        submission_id=submission.id,
        verifier_id=actor_id,
        decision=data.decision,
        notes=data.notes,
    )
    session.add(verification)
    return {"verification_id": str(verification.id), "decision": data.decision}
