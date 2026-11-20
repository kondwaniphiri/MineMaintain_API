from argparse import ArgumentParser
from datetime import UTC, datetime, timedelta
from getpass import getpass
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.config import DatabaseSettings
from app.core.security import password_hash
from app.db.models import Role, User
from app.db.session import build_engine
from app.db.workflow import (
    Asset,
    AssignmentEvent,
    AuditEvent,
    FaultReport,
    FaultStatus,
    Location,
    OrderStatus,
    Priority,
    WorkOrder,
)

DEMO_DOMAIN = "mopani-demo.example.com"
DEMO_ROLES = {
    "operator": Role.OPERATOR,
    "technician": Role.TECHNICIAN,
    "supervisor": Role.SUPERVISOR,
}


class DemoSettings(DatabaseSettings):
    environment: str = "local"


def seed(session: Session, password: str, orders: int) -> None:
    if session.scalar(select(Asset.id).limit(1)) or session.scalar(
        select(Location.id).limit(1)
    ):
        raise ValueError(
            "Seed requires an empty equipment register in a dedicated demo database"
        )
    emails = {role: f"{name}@{DEMO_DOMAIN}" for name, role in DEMO_ROLES.items()}
    if session.scalar(select(User.id).where(User.email.in_(emails.values())).limit(1)):
        raise ValueError("Demo accounts already exist")
    users = {
        role: User(
            id=uuid4(),
            email=email,
            full_name=f"Demo {role.value.title()}",
            roles=[role],
            password_hash=password_hash.hash(password),
        )
        for role, email in emails.items()
    }
    plant = Location(
        id=uuid4(),
        code="MOP-DEMO-PLANT",
        name="Mopani Copper Mines Demo Processing Area",
    )
    workshop = Location(
        id=uuid4(), code="MOP-DEMO-SHOP", name="Mopani Copper Mines Demo Workshop"
    )
    session.add_all([*users.values(), plant, workshop])
    session.flush()
    equipment = [
        Asset(
            id=uuid4(),
            asset_code=code,
            name=name,
            category=category,
            location_id=location.id,
        )
        for code, name, category, location in (
            ("PUMP-001", "Demo Process Water Pump", "Pump", plant),
            ("CONV-001", "Demo Feed Conveyor", "Conveyor", plant),
            ("COMP-001", "Demo Workshop Air Compressor", "Compressor", workshop),
        )
    ]
    session.add_all(equipment)
    session.flush()

    now = datetime.now(UTC)
    operator = users[Role.OPERATOR].id
    supervisor = users[Role.SUPERVISOR].id
    technician = users[Role.TECHNICIAN].id
    session.add(
        FaultReport(
            asset_id=equipment[0].id,
            reporter_id=operator,
            title="Pump vibration reported",
            symptoms="Unusual vibration reported during a fictional routine check.",
            observed_at=now,
            suggested_priority=Priority.MEDIUM,
        )
    )
    if not orders:
        return

    fault_ids = [uuid4() for _ in range(orders)]
    order_ids = [uuid4() for _ in range(orders)]
    titles = (
        "Reduced pump flow",
        "Conveyor stops intermittently",
        "Compressor cycles frequently",
    )
    session.execute(
        insert(FaultReport),
        [
            {
                "id": fault_id,
                "asset_id": equipment[index % len(equipment)].id,
                "reporter_id": operator,
                "title": f"{titles[index % len(titles)]} (sample {index + 1})",
                "symptoms": "Fictional maintenance scenario for local testing.",
                "observed_at": now,
                "suggested_priority": Priority.HIGH,
                "reviewed_priority": Priority.HIGH,
                "status": FaultStatus.CONVERTED,
                "version": 2,
            }
            for index, fault_id in enumerate(fault_ids)
        ],
    )
    session.execute(
        insert(WorkOrder),
        [
            {
                "id": order_id,
                "order_number": f"WO-{order_id.hex.upper()}",
                "fault_report_id": fault_id,
                "priority": Priority.HIGH,
                "assigned_to": technician,
                "status": OrderStatus.IN_PROGRESS,
                "due_at": now + timedelta(days=1),
                "started_at": now,
                "version": 3,
            }
            for order_id, fault_id in zip(order_ids, fault_ids, strict=True)
        ],
    )
    session.execute(
        insert(AssignmentEvent),
        [
            {
                "order_id": order_id,
                "to_user_id": technician,
                "actor_id": supervisor,
                "reason": "Fictional maintenance assignment",
            }
            for order_id in order_ids
        ],
    )
    session.execute(
        insert(AuditEvent),
        [
            {
                "actor_id": supervisor,
                "action": "ORDER_CREATED",
                "entity_type": "work_order",
                "entity_id": order_id,
                "changes": {},
                "request_id": uuid4(),
            }
            for order_id in order_ids
        ],
    )


def main() -> None:
    parser = ArgumentParser(
        description="Seed a local database with fictional Mopani Copper Mines demo data"
    )
    parser.add_argument("--orders", type=int, default=3)
    args = parser.parse_args()
    if not 0 <= args.orders <= 10_000:
        parser.error("Orders must be between 0 and 10000")
    settings = DemoSettings()
    if settings.environment not in {"local", "test"}:
        parser.error("Use a local or test database for the fictional fixtures")

    password = getpass("Demo password (minimum 12 characters): ")
    if not 12 <= len(password) <= 1024 or not password.strip():
        parser.error("Choose a demo password between 12 and 1024 characters")
    if password != getpass("Confirm demo password: "):
        parser.error("Passwords do not match")

    engine = build_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            seed(session, password, args.orders)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    finally:
        engine.dispose()
    print(
        f"Seeded two fictional locations, three assets, "
        f"three accounts at @{DEMO_DOMAIN}, "
        f"one submitted fault, and {args.orders} assigned orders."
    )


if __name__ == "__main__":
    main()
