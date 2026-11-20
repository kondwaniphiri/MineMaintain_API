from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.workflow import AuditEvent, IdempotencyRecord

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[!-~]+$"),
]


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Resource not found")


def check_version(resource, expected_version: int) -> None:
    if resource.version != expected_version:
        raise conflict("STALE_VERSION", "The resource has changed")


def commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise conflict(
                "DUPLICATE_RECORD", "A record with this identifier exists"
            ) from None
        raise


def audit(
    session: Session,
    request: Request,
    actor_id: UUID,
    action: str,
    entity_type: str,
    entity_id: UUID,
    **changes,
) -> None:
    session.add(
        AuditEvent(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=UUID(request.state.request_id),
            changes=changes,
        )
    )


def page_of(session, statement, model, page: int, page_size: int):
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    items = session.scalars(
        statement.order_by(model.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def idempotent(
    session: Session,
    actor_id: UUID,
    route: str,
    key: str,
    data: BaseModel,
    operation: Callable[[], BaseModel],
    *,
    location_prefix: str | None = None,
) -> JSONResponse:
    record = IdempotencyRecord
    identity = (record.actor_id == actor_id, record.route == route, record.key == key)
    now = datetime.now(UTC)
    digest = sha256(data.model_dump_json().encode()).hexdigest()

    expires_at = now + timedelta(hours=24)
    reservation = session.scalar(
        insert(record)
        .values(
            actor_id=actor_id,
            route=route,
            key=key,
            request_hash=digest,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            index_elements=["actor_id", "route", "key"],
            set_={
                "request_hash": digest,
                "expires_at": expires_at,
                "response_status": None,
                "response_body": None,
                "location": None,
            },
            where=record.expires_at <= now,
        )
        .returning(record)
    )
    if reservation is None:
        existing = session.scalar(select(record).where(*identity))
        if existing.request_hash != digest:
            raise conflict(
                "IDEMPOTENCY_CONFLICT", "The key was already used with different data"
            )
        status, body, location = (
            existing.response_status,
            existing.response_body,
            existing.location,
        )
    else:
        result = operation()
        status = 201 if location_prefix else 200
        body = result.model_dump(mode="json")
        location = f"{location_prefix}/{body['id']}" if location_prefix else None
        reservation.response_status = status
        reservation.response_body = body
        reservation.location = location
        expired = (
            select(record.id)
            .where(record.expires_at <= now)
            .order_by(record.expires_at, record.id)
            .limit(64)
            .with_for_update(skip_locked=True)
        )
        session.execute(delete(record).where(record.id.in_(expired)))
        commit(session)
    return JSONResponse(
        body, status, headers={"Location": location} if location else None
    )
