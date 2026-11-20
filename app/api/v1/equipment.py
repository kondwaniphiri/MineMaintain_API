from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from app.api.v1.auth import CurrentUser, require_roles
from app.core.errors import ApiError
from app.db.models import Role, User
from app.db.session import DbSession
from app.db.workflow import Asset, Lifecycle, Location
from app.schemas.workflow import (
    AssetCreate,
    AssetPatch,
    AssetRead,
    LocationCreate,
    LocationPatch,
    LocationRead,
    Page,
    Versioned,
)
from app.services.commands import audit, check_version, commit, not_found, page_of
from app.services.equipment import active_location, update_asset

router = APIRouter(tags=["equipment"])
Manager = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMINISTRATOR))]
PageNumber = Annotated[int, Query(ge=1, le=2_147_483_647)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def patch_fields(data: Versioned, nullable: set[str]) -> dict:
    changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    if not changes or any(
        value is None and field not in nullable for field, value in changes.items()
    ):
        raise ApiError(
            422, "VALIDATION_ERROR", "Supply at least one valid field to update"
        )
    return changes


@router.post("/locations", status_code=201)
def create_location(
    data: LocationCreate,
    request: Request,
    response: Response,
    actor: Manager,
    session: DbSession,
) -> LocationRead:
    location = Location(id=uuid4(), **data.model_dump())
    session.add(location)
    audit(session, request, actor.id, "LOCATION_CREATED", "location", location.id)
    commit(session)
    response.headers["Location"] = f"/api/v1/locations/{location.id}"
    return LocationRead.model_validate(location)


@router.get("/locations")
def list_locations(
    actor: CurrentUser,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    is_active: bool | None = None,
) -> Page[LocationRead]:
    statement = select(Location)
    if not {Role.SUPERVISOR, Role.ADMINISTRATOR}.intersection(actor.roles):
        statement = statement.where(Location.is_active.is_(True))
    if is_active is not None:
        statement = statement.where(Location.is_active.is_(is_active))
    return page_of(session, statement, Location, page, page_size)


@router.patch("/locations/{location_id}")
def patch_location(
    location_id: UUID,
    data: LocationPatch,
    request: Request,
    actor: Manager,
    session: DbSession,
) -> LocationRead:
    location = session.get(Location, location_id, with_for_update=True)
    if location is None:
        raise not_found()
    check_version(location, data.expected_version)
    changes = patch_fields(data, {"description"})
    for field, value in changes.items():
        setattr(location, field, value)
    location.version += 1
    audit(
        session,
        request,
        actor.id,
        "LOCATION_UPDATED",
        "location",
        location.id,
        fields=sorted(changes),
    )
    commit(session)
    return LocationRead.model_validate(location)


@router.get("/locations/{location_id}")
def get_location(
    location_id: UUID, actor: CurrentUser, session: DbSession
) -> LocationRead:
    location = session.get(Location, location_id)
    manager = bool({Role.SUPERVISOR, Role.ADMINISTRATOR}.intersection(actor.roles))
    if location is None or (not location.is_active and not manager):
        raise not_found()
    return LocationRead.model_validate(location)


@router.post("/assets", status_code=201)
def create_asset(
    data: AssetCreate,
    request: Request,
    response: Response,
    actor: Manager,
    session: DbSession,
) -> AssetRead:
    active_location(session, data.location_id)
    asset = Asset(id=uuid4(), **data.model_dump())
    session.add(asset)
    audit(session, request, actor.id, "ASSET_CREATED", "asset", asset.id)
    commit(session)
    response.headers["Location"] = f"/api/v1/assets/{asset.id}"
    return AssetRead.model_validate(asset)


@router.get("/assets")
def list_assets(
    actor: CurrentUser,
    session: DbSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    lifecycle: Lifecycle | None = None,
    location_id: UUID | None = None,
    asset_code: str | None = None,
) -> Page[AssetRead]:
    statement = select(Asset)
    for column, value in (
        (Asset.lifecycle, lifecycle),
        (Asset.location_id, location_id),
        (Asset.asset_code, asset_code),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return page_of(session, statement, Asset, page, page_size)


@router.get("/assets/{asset_id}")
def get_asset(asset_id: UUID, actor: CurrentUser, session: DbSession) -> AssetRead:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise not_found()
    return AssetRead.model_validate(asset)


@router.patch("/assets/{asset_id}")
def patch_asset(
    asset_id: UUID,
    data: AssetPatch,
    request: Request,
    actor: Manager,
    session: DbSession,
) -> AssetRead:
    asset = session.get(Asset, asset_id, with_for_update=True)
    if asset is None:
        raise not_found()
    check_version(asset, data.expected_version)
    changes = patch_fields(data, {"manufacturer", "model", "serial"})
    update_asset(session, asset, changes)
    audit(
        session,
        request,
        actor.id,
        "ASSET_UPDATED",
        "asset",
        asset.id,
        fields=sorted(changes),
    )
    commit(session)
    return AssetRead.model_validate(asset)
