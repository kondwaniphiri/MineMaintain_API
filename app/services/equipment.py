from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.workflow import TERMINAL, Asset, FaultReport, Lifecycle, Location, WorkOrder
from app.services.commands import conflict, not_found


def active_location(session: Session, location_id) -> None:
    location = session.get(Location, location_id, with_for_update={"read": True})
    if location is None:
        raise not_found()
    if not location.is_active:
        raise conflict("LOCATION_INACTIVE", "Location is inactive")


def active_asset(session: Session, asset_id) -> Asset:
    asset = session.get(Asset, asset_id, with_for_update={"read": True})
    if asset is None:
        raise not_found()
    if asset.lifecycle == Lifecycle.RETIRED:
        raise conflict("ASSET_RETIRED", "Asset is retired")
    return asset


def update_asset(session: Session, asset: Asset, changes: dict) -> None:
    if "location_id" in changes:
        active_location(session, changes["location_id"])
    if (
        changes.get("lifecycle") == Lifecycle.RETIRED
        and asset.lifecycle != Lifecycle.RETIRED
    ):
        has_open_order = (
            select(WorkOrder.id)
            .join(FaultReport)
            .where(FaultReport.asset_id == asset.id, WorkOrder.status.not_in(TERMINAL))
            .exists()
        )
        if session.scalar(select(has_open_order)):
            raise conflict("ACTIVE_WORK_ORDERS", "Asset has nonterminal work orders")
    for field, value in changes.items():
        setattr(asset, field, value)
    asset.version += 1
