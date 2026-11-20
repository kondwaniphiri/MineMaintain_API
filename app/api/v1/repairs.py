from uuid import UUID

from fastapi import APIRouter, Request

from app.api.v1.faults import Supervisor
from app.api.v1.orders import Technician, order_command
from app.db.session import DbSession
from app.schemas.repairs import (
    AddLabour,
    AddNote,
    AddPart,
    Correction,
    SubmitRepair,
    VerifyRepair,
)
from app.schemas.workflow import OrderRead
from app.services.commands import IdempotencyKey
from app.services.repairs import (
    append_record,
    correct_record,
    submit_repair,
    verify_repair,
)

router = APIRouter(prefix="/work-orders", tags=["repair records"])


@router.post("/{order_id}/notes")
def add_note(
    order_id: UUID,
    data: AddNote,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    return order_command(
        session,
        request,
        actor,
        order_id,
        "notes",
        key,
        data,
        lambda order: append_record(session, order, actor.id, "note", data),
        technician=True,
    )


@router.post("/{order_id}/labour")
def add_labour(
    order_id: UUID,
    data: AddLabour,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    return order_command(
        session,
        request,
        actor,
        order_id,
        "labour",
        key,
        data,
        lambda order: append_record(session, order, actor.id, "labour", data),
        technician=True,
    )


@router.post("/{order_id}/parts-used")
def add_part(
    order_id: UUID,
    data: AddPart,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    return order_command(
        session,
        request,
        actor,
        order_id,
        "parts-used",
        key,
        data,
        lambda order: append_record(session, order, actor.id, "part", data),
        technician=True,
    )


@router.post("/{order_id}/corrections")
def correct(
    order_id: UUID,
    data: Correction,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    return order_command(
        session,
        request,
        actor,
        order_id,
        "corrections",
        key,
        data,
        lambda order: correct_record(session, order, actor.id, data),
        technician=True,
    )


@router.post("/{order_id}/submit-for-verification")
def submit(
    order_id: UUID,
    data: SubmitRepair,
    key: IdempotencyKey,
    request: Request,
    actor: Technician,
    session: DbSession,
) -> OrderRead:
    return order_command(
        session,
        request,
        actor,
        order_id,
        "submit-for-verification",
        key,
        data,
        lambda order: submit_repair(session, order, actor.id, data),
        technician=True,
    )


@router.post("/{order_id}/verification")
def verify(
    order_id: UUID,
    data: VerifyRepair,
    key: IdempotencyKey,
    request: Request,
    actor: Supervisor,
    session: DbSession,
) -> OrderRead:
    return order_command(
        session,
        request,
        actor,
        order_id,
        "verification",
        key,
        data,
        lambda order: verify_repair(session, order, actor.id, data),
    )
