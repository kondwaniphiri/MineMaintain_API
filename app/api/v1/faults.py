from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.api.v1.auth import CurrentUser, require_roles
from app.api.v1.equipment import PageNumber, PageSize
from app.db.models import Role, User
from app.db.session import DbSession
from app.db.workflow import FaultReport, FaultStatus, WorkOrder
from app.schemas.workflow import (
    Convert,
    Dismiss,
    FaultCreate,
    FaultRead,
    OrderRead,
    Page,
)
from app.services.commands import (
    IdempotencyKey,
    audit,
    commit,
    idempotent,
    not_found,
    page_of,
)
from app.services.equipment import active_asset
from app.services.workflow import convert, dismiss, fault_view, submitted_fault

router = APIRouter(prefix="/fault-reports", tags=["fault reports"])
Supervisor = Annotated[User, Depends(require_roles(Role.SUPERVISOR))]
FAULTS = "/api/v1/fault-reports"
ORDERS = "/api/v1/work-orders"


def visible_reports(actor: User):
    statement = select(FaultReport)
    if Role.SUPERVISOR not in actor.roles:
        statement = statement.where(FaultReport.reporter_id == actor.id)
    return statement


@router.post("", status_code=201)
def create_fault(
    data: FaultCreate,
    key: IdempotencyKey,
    request: Request,
    actor: CurrentUser,
    session: DbSession,
) -> FaultRead:
    def operation() -> FaultRead:
        active_asset(session, data.asset_id)
        report = FaultReport(id=uuid4(), reporter_id=actor.id, **data.model_dump())
        session.add(report)
        audit(session, request, actor.id, "FAULT_REPORTED", "fault_report", report.id)
        session.flush()
        return fault_view(report, None)

    return idempotent(
        session, actor.id, FAULTS, key, data, operation, location_prefix=FAULTS
    )


@router.get("")
def list_faults(
    actor: CurrentUser,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    asset_id: UUID | None = None,
    status: FaultStatus | None = None,
) -> Page[FaultRead]:
    statement = visible_reports(actor)
    if asset_id is not None:
        statement = statement.where(FaultReport.asset_id == asset_id)
    if status is not None:
        statement = statement.where(FaultReport.status == status)
    result = page_of(session, statement, FaultReport, page, page_size)
    reports = result["items"]
    orders = {
        order.fault_report_id: order
        for order in session.scalars(
            select(WorkOrder).where(
                WorkOrder.fault_report_id.in_([report.id for report in reports])
            )
        )
    }
    result["items"] = [fault_view(report, orders.get(report.id)) for report in reports]
    return result


@router.get("/{report_id}")
def get_fault(report_id: UUID, actor: CurrentUser, session: DbSession) -> FaultRead:
    report = session.scalar(visible_reports(actor).where(FaultReport.id == report_id))
    if report is None:
        raise not_found()
    order = session.scalar(
        select(WorkOrder).where(WorkOrder.fault_report_id == report.id)
    )
    return fault_view(report, order)


@router.post("/{report_id}/dismiss")
def dismiss_fault(
    report_id: UUID,
    data: Dismiss,
    request: Request,
    actor: Supervisor,
    session: DbSession,
) -> FaultRead:
    report = submitted_fault(session, report_id, data.expected_version)
    dismiss(session, report, data)
    audit(session, request, actor.id, "FAULT_DISMISSED", "fault_report", report.id)
    result = fault_view(report, None)
    commit(session)
    return result


@router.post("/{report_id}/work-order", status_code=201)
def convert_fault(
    report_id: UUID,
    data: Convert,
    key: IdempotencyKey,
    request: Request,
    actor: Supervisor,
    session: DbSession,
) -> OrderRead:
    def operation() -> OrderRead:
        report = submitted_fault(session, report_id, data.expected_version)
        active_asset(session, report.asset_id)
        order = convert(session, report, data)
        audit(
            session,
            request,
            actor.id,
            "FAULT_CONVERTED",
            "fault_report",
            report.id,
            order_id=str(order.id),
        )
        audit(
            session,
            request,
            actor.id,
            "ORDER_CREATED",
            "work_order",
            order.id,
            priority=data.priority,
            review_notes=data.review_notes,
        )
        session.flush()
        return OrderRead.model_validate(order)

    route = f"{FAULTS}/{report_id}/work-order"
    return idempotent(
        session, actor.id, route, key, data, operation, location_prefix=ORDERS
    )
