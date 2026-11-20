from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import and_, select

from app.api.v1.auth import require_roles
from app.api.v1.equipment import PageNumber, PageSize, patch_fields
from app.core.security import password_hash
from app.db.models import Role, User
from app.db.session import DbSession
from app.db.workflow import AuditEvent
from app.schemas.repairs import HistoryEvent
from app.schemas.users import Account, UserCreate, UserPatch
from app.schemas.workflow import Page
from app.services.commands import audit, check_version, commit, not_found, page_of
from app.services.history import timeline

router = APIRouter(prefix="/users", tags=["users"])
Administrator = Annotated[User, Depends(require_roles(Role.ADMINISTRATOR))]


@router.post("", status_code=201)
def create_user(
    data: UserCreate,
    request: Request,
    response: Response,
    actor: Administrator,
    session: DbSession,
) -> Account:
    user = User(
        id=uuid4(),
        email=data.email,
        full_name=data.full_name,
        password_hash=password_hash.hash(data.password.get_secret_value()),
        roles=data.roles,
    )
    session.add(user)
    audit(session, request, actor.id, "USER_CREATED", "user", user.id, roles=user.roles)
    commit(session)
    response.headers["Location"] = f"/api/v1/users/{user.id}"
    return Account.model_validate(user)


@router.get("")
def list_users(
    actor: Administrator,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[Account]:
    return page_of(session, select(User), User, page, page_size)


@router.get("/{user_id}")
def read_user(user_id: UUID, actor: Administrator, session: DbSession) -> Account:
    user = session.get(User, user_id)
    if user is None:
        raise not_found()
    return Account.model_validate(user)


@router.get("/{user_id}/history")
def user_history(
    user_id: UUID,
    actor: Administrator,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[HistoryEvent]:
    if session.get(User, user_id) is None:
        raise not_found()
    scope = and_(AuditEvent.entity_type == "user", AuditEvent.entity_id == user_id)
    return timeline(session, None, scope, page, page_size)


@router.patch("/{user_id}")
def patch_user(
    user_id: UUID,
    data: UserPatch,
    request: Request,
    actor: Administrator,
    session: DbSession,
) -> Account:
    user = session.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise not_found()
    check_version(user, data.expected_version)
    changes = patch_fields(data, set())
    for field, value in changes.items():
        setattr(user, field, value)
    user.version += 1
    audit(
        session,
        request,
        actor.id,
        "USER_UPDATED",
        "user",
        user.id,
        fields=sorted(changes),
        roles=user.roles,
        is_active=user.is_active,
    )
    commit(session)
    return Account.model_validate(user)
