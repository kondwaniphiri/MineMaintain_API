from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.v1.faults import Supervisor
from app.db.session import DbSession
from app.db.workflow import AuditEvent, OrderStatus, Priority, WorkOrder
from app.schemas.repairs import MaintenanceSummary
from app.services.workflow import overdue_at

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/maintenance-summary")
def maintenance_summary(actor: Supervisor, session: DbSession) -> MaintenanceSummary:
    now = datetime.now(UTC)
    by_status = dict.fromkeys(OrderStatus, 0)
    by_priority = dict.fromkeys(Priority, 0)
    overdue = 0
    for status, priority, count, late in session.execute(
        select(
            WorkOrder.status,
            WorkOrder.priority,
            func.count(),
            func.count().filter(overdue_at(now)),
        ).group_by(WorkOrder.status, WorkOrder.priority)
    ):
        by_status[status] += count
        by_priority[priority] += count
        overdue += late

    created = (
        select(AuditEvent.entity_id, func.min(AuditEvent.created_at).label("time"))
        .where(
            AuditEvent.entity_type == "work_order", AuditEvent.action == "ORDER_CREATED"
        )
        .group_by(AuditEvent.entity_id)
        .subquery()
    )
    seconds = session.scalar(
        select(func.avg(func.extract("epoch", WorkOrder.closed_at - created.c.time)))
        .join(created, created.c.entity_id == WorkOrder.id)
        .where(WorkOrder.status == OrderStatus.CLOSED)
    )
    return MaintenanceSummary(
        by_status=by_status,
        by_priority=by_priority,
        overdue_count=overdue,
        average_closure_seconds=float(seconds) if seconds is not None else None,
    )
