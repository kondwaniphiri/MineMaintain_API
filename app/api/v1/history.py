from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import and_, or_, select

from app.api.v1.auth import CurrentUser
from app.api.v1.equipment import PageNumber, PageSize
from app.db.models import Role
from app.db.session import DbSession
from app.db.workflow import Asset, AuditEvent, FaultReport, WorkOrder
from app.schemas.repairs import HistoryEvent
from app.schemas.workflow import Page
from app.services.commands import not_found
from app.services.history import timeline
from app.services.workflow import get_order, visible_orders

router = APIRouter(tags=["maintenance history"])


@router.get("/work-orders/{order_id}/history")
def order_history(
    order_id: UUID,
    actor: CurrentUser,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[HistoryEvent]:
    order = get_order(session, order_id, actor, shared=True)
    order_ids = select(WorkOrder.id).where(WorkOrder.id == order.id)
    events = and_(
        AuditEvent.entity_type == "work_order", AuditEvent.entity_id == order.id
    )
    return timeline(session, order_ids, events, page, page_size)


@router.get("/assets/{asset_id}/maintenance-history")
def asset_history(
    asset_id: UUID,
    actor: CurrentUser,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[HistoryEvent]:
    orders = (
        visible_orders(actor).join(FaultReport).where(FaultReport.asset_id == asset_id)
    )
    order_ids = orders.with_only_columns(WorkOrder.id)
    events = and_(
        AuditEvent.entity_type == "work_order", AuditEvent.entity_id.in_(order_ids)
    )
    if Role.SUPERVISOR in actor.roles:
        if session.get(Asset, asset_id) is None:
            raise not_found()
        fault_ids = select(FaultReport.id).where(FaultReport.asset_id == asset_id)
        events = or_(
            events,
            and_(AuditEvent.entity_type == "asset", AuditEvent.entity_id == asset_id),
            and_(
                AuditEvent.entity_type == "fault_report",
                AuditEvent.entity_id.in_(fault_ids),
            ),
        )
    elif session.scalar(select(order_ids.exists())) is False:
        raise not_found()
    return timeline(session, order_ids, events, page, page_size)
