from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session, aliased

from app.db.repairs import LabourEntry, PartUsage, RepairSubmission, Verification
from app.db.workflow import AssignmentEvent, AuditEvent, WorkNote


def timeline(session: Session, order_ids, other_events, page: int, page_size: int):
    events = select(
        AuditEvent.id,
        AuditEvent.entity_id.label("resource_id"),
        AuditEvent.entity_type,
        AuditEvent.action,
        AuditEvent.actor_id,
        AuditEvent.created_at,
        AuditEvent.changes.label("details"),
        AuditEvent.request_id,
    ).where(other_events)
    if order_ids is None:
        return page_of_events(session, events.subquery(), page, page_size)

    def record(model, actor, event_type, timestamp, **fields):
        details = func.jsonb_build_object(
            *(value for key, value in fields.items() for value in (literal(key), value))
        )
        return select(
            model.id,
            model.order_id,
            literal("work_order"),
            literal(event_type),
            actor,
            timestamp,
            details,
            literal(None, type_=AuditEvent.request_id.type),
        ).where(model.order_id.in_(order_ids))

    history = union_all(
        events,
        record(
            AssignmentEvent,
            AssignmentEvent.actor_id,
            "ASSIGNMENT_RECORDED",
            AssignmentEvent.created_at,
            from_user_id=AssignmentEvent.from_user_id,
            to_user_id=AssignmentEvent.to_user_id,
            reason=AssignmentEvent.reason,
        ),
        record(
            WorkNote,
            WorkNote.author_id,
            "NOTE_RECORDED",
            WorkNote.created_at,
            kind=WorkNote.kind,
            text=WorkNote.text,
            supersedes_id=WorkNote.supersedes_id,
            correction_reason=WorkNote.correction_reason,
        ),
        record(
            LabourEntry,
            LabourEntry.technician_id,
            "LABOUR_RECORDED",
            LabourEntry.created_at,
            minutes=LabourEntry.minutes,
            work_date=LabourEntry.work_date,
            description=LabourEntry.description,
            supersedes_id=LabourEntry.supersedes_id,
            correction_reason=LabourEntry.correction_reason,
        ),
        record(
            PartUsage,
            PartUsage.technician_id,
            "PART_RECORDED",
            PartUsage.recorded_at,
            part_code=PartUsage.part_code,
            description=PartUsage.description,
            quantity=func.to_char(PartUsage.quantity, "FM9999999990.0000"),
            unit=PartUsage.unit,
            supersedes_id=PartUsage.supersedes_id,
            correction_reason=PartUsage.correction_reason,
        ),
        record(
            RepairSubmission,
            RepairSubmission.technician_id,
            "REPAIR_SUBMITTED",
            RepairSubmission.created_at,
            diagnosis=RepairSubmission.diagnosis,
            repair_summary=RepairSubmission.repair_summary,
            test_results=RepairSubmission.test_results,
            external_reference=RepairSubmission.external_reference,
        ),
        record(
            Verification,
            Verification.verifier_id,
            "VERIFICATION_RECORDED",
            Verification.created_at,
            submission_id=Verification.submission_id,
            decision=Verification.decision,
            notes=Verification.notes,
        ),
    ).subquery()
    return page_of_events(session, history, page, page_size)


def page_of_events(session: Session, history, page: int, page_size: int):
    items = (
        session.execute(
            select(history)
            .order_by(history.c.created_at, history.c.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .mappings()
        .all()
    )
    total = session.scalar(select(func.count()).select_from(history))
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def current_entries(model, order_id):
    replacement = aliased(model)
    return (
        model.order_id == order_id,
        ~select(replacement.id).where(replacement.supersedes_id == model.id).exists(),
    )


def repair_totals(session: Session, order_id):
    minutes = session.scalar(
        select(func.coalesce(func.sum(LabourEntry.minutes), 0)).where(
            *current_entries(LabourEntry, order_id)
        )
    )
    parts = (
        session.execute(
            select(
                PartUsage.part_code,
                PartUsage.unit,
                func.sum(PartUsage.quantity).label("quantity"),
            )
            .where(*current_entries(PartUsage, order_id))
            .group_by(PartUsage.part_code, PartUsage.unit)
            .order_by(PartUsage.part_code, PartUsage.unit)
        )
        .mappings()
        .all()
    )
    return {"labour_minutes": minutes, "parts": parts}
