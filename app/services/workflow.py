from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import Role, User
from app.db.workflow import (
    TERMINAL,
    AssignmentEvent,
    FaultReport,
    FaultStatus,
    NoteKind,
    OrderStatus,
    WorkNote,
    WorkOrder,
)
from app.schemas.workflow import (
    Assignment,
    Cancel,
    Convert,
    Dismiss,
    FaultRead,
    OrderSummary,
)
from app.services.commands import check_version, conflict, not_found


def fault_view(report: FaultReport, order: WorkOrder | None) -> FaultRead:
    return FaultRead.model_validate(report).model_copy(
        update={"work_order": OrderSummary.model_validate(order) if order else None}
    )


def submitted_fault(session: Session, report_id: UUID, version: int) -> FaultReport:
    report = session.get(FaultReport, report_id, with_for_update=True)
    if report is None:
        raise not_found()
    check_version(report, version)
    if report.status != FaultStatus.SUBMITTED:
        raise conflict(
            "INVALID_TRANSITION", "Only submitted fault reports may be triaged"
        )
    return report


def dismiss(session: Session, report: FaultReport, data: Dismiss) -> None:
    if data.related_report_id:
        if data.related_report_id == report.id:
            raise ApiError(422, "VALIDATION_ERROR", "A report cannot reference itself")
        related = session.get(FaultReport, data.related_report_id)
        if related is None:
            raise not_found()
        if related.asset_id != report.asset_id:
            raise conflict(
                "UNRELATED_REPORT", "Related report must concern the same asset"
            )
    report.status = FaultStatus.DISMISSED
    report.dismissal_reason = data.reason
    report.related_report_id = data.related_report_id
    report.version += 1


def convert(session: Session, report: FaultReport, data: Convert) -> WorkOrder:
    order_id = uuid4()
    order = WorkOrder(
        id=order_id,
        order_number=f"WO-{order_id.hex.upper()}",
        fault_report_id=report.id,
        priority=data.priority,
    )
    session.add(order)
    report.status = FaultStatus.CONVERTED
    report.reviewed_priority = data.priority
    report.version += 1
    return order


def visible_orders(actor: User):
    statement = select(WorkOrder)
    if Role.SUPERVISOR in actor.roles:
        return statement
    if Role.TECHNICIAN in actor.roles:
        return statement.where(WorkOrder.assigned_to == actor.id)
    raise ApiError(403, "FORBIDDEN", "Insufficient permissions")


def overdue_at(now: datetime):
    return and_(
        WorkOrder.due_at.is_not(None),
        WorkOrder.due_at < now,
        WorkOrder.status.not_in(TERMINAL),
    )


def get_order(
    session: Session,
    order_id: UUID,
    actor: User,
    *,
    locked=False,
    technician=False,
    shared=False,
):
    statement = visible_orders(actor).where(WorkOrder.id == order_id)
    if technician:
        statement = statement.where(WorkOrder.assigned_to == actor.id)
    if locked:
        statement = statement.with_for_update()
    elif shared:
        statement = statement.with_for_update(read=True)
    order = session.scalar(statement)
    if order is None:
        raise not_found()
    return order


def transition(
    order: WorkOrder, allowed: tuple[OrderStatus, ...], target: OrderStatus
) -> None:
    if order.status not in allowed:
        raise conflict(
            "INVALID_TRANSITION",
            "Action is unavailable in the current work order state",
        )
    order.status = target
    order.version += 1


def assign(
    session: Session, order: WorkOrder, actor_id: UUID, data: Assignment
) -> None:
    allowed = (
        OrderStatus.OPEN,
        OrderStatus.ASSIGNED,
        OrderStatus.IN_PROGRESS,
        OrderStatus.AWAITING_PARTS,
    )
    target = OrderStatus.ASSIGNED if order.status == OrderStatus.OPEN else order.status
    transition(order, allowed, target)
    # Suppress autoflush so the order's pending state is written only after validation.
    with session.no_autoflush:
        technician = session.scalar(
            select(User)
            .where(User.id == data.technician_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    if (
        technician is None
        or not technician.is_active
        or Role.TECHNICIAN not in technician.roles
    ):
        raise conflict("INVALID_ASSIGNEE", "Assignee must be an active technician")
    if data.due_at <= datetime.now(UTC):
        raise ApiError(422, "VALIDATION_ERROR", "Due date must be in the future")
    session.add(
        AssignmentEvent(
            order_id=order.id,
            from_user_id=order.assigned_to,
            to_user_id=technician.id,
            actor_id=actor_id,
            reason=data.reason,
        )
    )
    order.assigned_to = technician.id
    order.due_at = data.due_at


def add_progress(session: Session, order: WorkOrder, actor_id: UUID, note: str) -> None:
    session.add(
        WorkNote(
            order_id=order.id, author_id=actor_id, kind=NoteKind.PROGRESS, text=note
        )
    )


def cancel(order: WorkOrder, data: Cancel) -> None:
    active = (OrderStatus.IN_PROGRESS, OrderStatus.AWAITING_PARTS)
    allowed = (OrderStatus.OPEN, OrderStatus.ASSIGNED, *active)
    if order.status in active and data.handover_note is None:
        raise ApiError(
            422, "VALIDATION_ERROR", "A handover note is required for active work"
        )
    transition(order, allowed, OrderStatus.CANCELLED)
