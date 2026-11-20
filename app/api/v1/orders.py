from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import not_

from app.api.v1.auth import CurrentUser, require_roles
from app.api.v1.equipment import PageNumber, PageSize
from app.api.v1.faults import ORDERS, Supervisor
from app.db.models import Role, User
from app.db.session import DbSession
from app.db.workflow import FaultReport, OrderStatus, Priority, WorkOrder
from app.schemas.repairs import OrderDetail
from app.schemas.workflow import (
    Assignment,
    Cancel,
    OrderRead,
    Page,
    Pause,
    Versioned,
    WorkNote,
)
from app.services.commands import (
    IdempotencyKey,
    audit,
    check_version,
    idempotent,
    page_of,
)
from app.services.history import repair_totals
from app.services.workflow import (
    add_progress,
    assign,
    cancel,
    get_order,
    overdue_at,
    transition,
    visible_orders,
)

router = APIRouter(prefix="/work-orders", tags=["work orders"])
Technician = Annotated[User, Depends(require_roles(Role.TECHNICIAN))]


@router.get("")
def list_orders(
    actor: CurrentUser,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    status: OrderStatus | None = None,
    priority: Priority | None = None,
    asset_id: UUID | None = None,
    assigned_to: UUID | None = None,
    overdue: bool | None = None,
) -> Page[OrderRead]:
    statement = visible_orders(actor)
    for column, value in (
        (WorkOrder.status, status),
        (WorkOrder.priority, priority),
        (WorkOrder.assigned_to, assigned_to),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if asset_id is not None:
        statement = statement.join(FaultReport).where(FaultReport.asset_id == asset_id)
    if overdue is not None:
        past_due = overdue_at(datetime.now(UTC))
        statement = statement.where(past_due if overdue else not_(past_due))
    return page_of(session, statement, WorkOrder, page, page_size)


@router.get("/{order_id}")
def read_order(order_id: UUID, actor: CurrentUser, session: DbSession) -> OrderDetail:
    order = OrderRead.model_validate(get_order(session, order_id, actor, shared=True))
    return OrderDetail(**order.model_dump(), totals=repair_totals(session, order_id))


def order_command(
    session: DbSession,
    request: Request,
    actor: User,
    order_id: UUID,
    command: str,
    key: str,
    data: Versioned,
    mutate: Callable[[WorkOrder], dict],
    *,
    technician: bool = False,
):
    order = get_order(session, order_id, actor, locked=True, technician=technician)

    def operation() -> OrderRead:
        check_version(order, data.expected_version)
        changes = mutate(order)
        audit(
            session,
            request,
            actor.id,
            f"ORDER_{command.upper().replace('-', '_')}",
            "work_order",
            order_id,
            status=order.status,
            version=order.version,
            **changes,
        )
        return OrderRead.model_validate(order)

    return idempotent(
        session, actor.id, f"{ORDERS}/{order_id}/{command}", key, data, operation
    )


@router.post("/{order_id}/assignment")
def set_assignment(
    order_id: UUID,
    data: Assignment,
    key: IdempotencyKey,
    request: Request,
    actor: Supervisor,
    session: DbSession,
) -> OrderRead:
    def mutate(order: WorkOrder) -> dict:
        assign(session, order, actor.id, data)
        return {
            "assigned_to": str(data.technician_id),
            "due_at": data.due_at.isoformat(),
        }

    return order_command(
        session, request, actor, order_id, "assignment", key, data, mutate
    )


@router.post("/{order_id}/start")
def start(
    order_id: UUID,
    data: WorkNote,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    def mutate(order: WorkOrder) -> dict:
        transition(order, (OrderStatus.ASSIGNED,), OrderStatus.IN_PROGRESS)
        order.started_at = datetime.now(UTC)
        add_progress(session, order, actor.id, data.note)
        return {}

    return order_command(
        session, request, actor, order_id, "start", key, data, mutate, technician=True
    )


@router.post("/{order_id}/pause-for-parts")
def pause(
    order_id: UUID,
    data: Pause,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    def mutate(order: WorkOrder) -> dict:
        transition(order, (OrderStatus.IN_PROGRESS,), OrderStatus.AWAITING_PARTS)
        return {"reason": data.reason}

    return order_command(
        session,
        request,
        actor,
        order_id,
        "pause-for-parts",
        key,
        data,
        mutate,
        technician=True,
    )


@router.post("/{order_id}/resume")
def resume(
    order_id: UUID,
    data: WorkNote,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    def mutate(order: WorkOrder) -> dict:
        transition(order, (OrderStatus.AWAITING_PARTS,), OrderStatus.IN_PROGRESS)
        add_progress(session, order, actor.id, data.note)
        return {}

    return order_command(
        session, request, actor, order_id, "resume", key, data, mutate, technician=True
    )


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: UUID,
    data: Cancel,
    key: IdempotencyKey,
    request: Request,
    actor: Supervisor,
    session: DbSession,
) -> OrderRead:
    def mutate(order: WorkOrder) -> dict:
        cancel(order, data)
        return {"reason": data.reason, "handover_note": data.handover_note}

    return order_command(session, request, actor, order_id, "cancel", key, data, mutate)
