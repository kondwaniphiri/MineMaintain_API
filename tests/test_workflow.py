from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.security import issue_token, password_hash
from app.db.models import Role, User
from app.db.workflow import AssignmentEvent, AuditEvent, WorkNote, WorkOrder
from app.main import create_app


@pytest.fixture
def workflow(database):
    settings, engine = database
    with Session(engine) as session, session.begin():
        user = User(
            email="admin@example.com",
            full_name="Administrator",
            roles=[Role.ADMINISTRATOR],
            password_hash=password_hash.hash(token_urlsafe()),
        )
        session.add(user)
        session.flush()
        admin = {"Authorization": f"Bearer {issue_token(user.id, settings)}"}

    with TestClient(
        create_app(settings), base_url="http://localhost/api/v1/"
    ) as client:
        headers = {"admin": admin}
        ids = {}
        for name, role in (
            ("operator", Role.OPERATOR),
            ("supervisor", Role.SUPERVISOR),
            ("tech", Role.TECHNICIAN),
            ("other", Role.TECHNICIAN),
        ):
            response = client.post(
                "users",
                headers=admin,
                json={
                    "email": f"{name}@example.com",
                    "full_name": name,
                    "password": token_urlsafe(),
                    "roles": [role],
                },
            )
            assert response.status_code == 201, response.text
            ids[name] = response.json()["id"]
            headers[name] = {
                "Authorization": f"Bearer {issue_token(UUID(ids[name]), settings)}"
            }

        response = client.post(
            "locations", headers=admin, json={"code": "PLANT", "name": "Plant"}
        )
        assert response.status_code == 201, response.text
        asset = client.post(
            "assets",
            headers=admin,
            json={
                "asset_code": "PUMP-001",
                "name": "Pump",
                "category": "Pump Type",
                "location_id": response.json()["id"],
            },
        )
        assert asset.status_code == 201, asset.text
        yield client, engine, headers, ids, asset.json()["id"]


def command(client, path, headers, key, payload):
    return client.post(path, headers={**headers, "Idempotency-Key": key}, json=payload)


def report_fault(client, headers, asset_id, key="fault"):
    return command(
        client,
        "fault-reports",
        headers,
        key,
        {
            "asset_id": asset_id,
            "title": "Pump failed",
            "symptoms": "Pump stopped",
            "observed_at": "2026-11-20T12:00:00+02:00",
            "suggested_priority": "HIGH",
        },
    )


def test_equipment_fault_and_order_workflow(workflow):
    client, engine, headers, ids, asset_id = workflow
    operator, supervisor, tech = (
        headers[name] for name in ("operator", "supervisor", "tech")
    )
    response = report_fault(client, operator, asset_id)
    assert response.status_code == 201, response.text
    assert response.json()["observed_at"] == "2026-11-20T10:00:00Z"
    assert report_fault(client, operator, asset_id).json() == response.json()
    assert client.get("fault-reports", headers=headers["admin"]).json()["total"] == 0
    report_path = f"fault-reports/{response.json()['id']}"
    conversion = f"{report_path}/work-order"
    payload = {
        "expected_version": 1,
        "priority": "HIGH",
        "review_notes": "Inspect pump",
    }
    assert command(client, conversion, operator, "convert", payload).status_code == 403
    response = command(client, conversion, supervisor, "convert", payload)
    assert response.status_code == 201, response.text
    assert (
        command(client, conversion, supervisor, "convert", payload).json()
        == response.json()
    )
    mismatch = command(
        client, conversion, supervisor, "convert", {**payload, "priority": "LOW"}
    )
    assert mismatch.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    order = response.json()
    order_path = f"work-orders/{order['id']}"
    summary = client.get(report_path, headers=operator).json()["work_order"]
    assert set(summary) == {"id", "order_number", "priority", "status"}
    assert client.get(order_path, headers=operator).status_code == 403
    assert client.get(order_path, headers=tech).status_code == 404
    assert client.get(order_path, headers=headers["admin"]).status_code == 403
    retirement = {"expected_version": 1, "lifecycle": "RETIRED"}
    assert (
        client.patch(
            f"assets/{asset_id}", headers=supervisor, json=retirement
        ).status_code
        == 409
    )

    assignment = {
        "expected_version": 1,
        "technician_id": ids["tech"],
        "reason": "Investigate failure",
        "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    assert (
        command(
            client, f"{order_path}/assignment", supervisor, "assign", assignment
        ).status_code
        == 200
    )
    assert client.get("work-orders?overdue=false", headers=tech).json()["total"] == 1
    with Session(engine) as session, session.begin():
        session.get(WorkOrder, UUID(order["id"])).due_at = datetime.now(
            UTC
        ) - timedelta(days=1)
    assert (
        client.get(
            "work-orders?overdue=true&status=ASSIGNED&priority=HIGH", headers=tech
        ).json()["total"]
        == 1
    )
    assert (
        client.get("reports/maintenance-summary", headers=supervisor).json()[
            "overdue_count"
        ]
        == 1
    )
    start = {"expected_version": 2, "note": "Inspection started"}
    assert (
        command(
            client, f"{order_path}/start", headers["other"], "start", start
        ).status_code
        == 404
    )
    assert (
        command(client, f"{order_path}/start", tech, "start", start).json()["status"]
        == "IN_PROGRESS"
    )
    stale = {"expected_version": 2, "reason": "Waiting on bearing"}
    rejection = command(client, f"{order_path}/pause-for-parts", tech, "pause", stale)
    assert rejection.json()["error"]["code"] == "STALE_VERSION"
    pause = {**stale, "expected_version": 3}

    def pause_attempt(key):
        return key, command(client, f"{order_path}/pause-for-parts", tech, key, pause)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(pause_attempt, ["pause", "competing-pause"]))
    assert sorted(result.status_code for _, result in outcomes) == [200, 409]
    winner, response = next(pair for pair in outcomes if pair[1].status_code == 200)
    assert command(
        client, f"{order_path}/pause-for-parts", tech, winner, pause
    ).json() == (response.json())
    assert response.json()["status"] == "AWAITING_PARTS"
    resume = {"expected_version": 4, "note": "Bearing arrived"}
    assert (
        command(client, f"{order_path}/resume", tech, "resume", resume).json()[
            "version"
        ]
        == 5
    )

    reassignment = {**assignment, "expected_version": 5, "technician_id": ids["other"]}
    response = command(
        client, f"{order_path}/assignment", supervisor, "reassign", reassignment
    )
    assert response.json()["status"] == "IN_PROGRESS"
    assert client.get(order_path, headers=tech).status_code == 404
    assert (
        command(client, f"{order_path}/resume", tech, "resume", resume).status_code
        == 404
    )
    cancel = {"expected_version": 6, "reason": "Scope changed"}
    assert (
        command(
            client, f"{order_path}/cancel", supervisor, "cancel", cancel
        ).status_code
        == 422
    )
    cancel["handover_note"] = "Inspection documented"
    response = command(client, f"{order_path}/cancel", supervisor, "cancel", cancel)
    assert response.json()["status"] == "CANCELLED"
    assert (
        client.patch(
            f"assets/{asset_id}", headers=supervisor, json=retirement
        ).status_code
        == 200
    )
    assert (
        report_fault(client, operator, asset_id, "new-fault").json()["error"]["code"]
        == "ASSET_RETIRED"
    )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AssignmentEvent)) == 2
        assert session.scalar(select(func.count()).select_from(WorkNote)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == UUID(order["id"]))
            )
            == 7
        )


def test_concurrent_conversion(workflow):
    client, engine, headers, _, asset_id = workflow
    response = report_fault(client, headers["operator"], asset_id)
    path = f"fault-reports/{response.json()['id']}/work-order"
    barrier = Barrier(3)

    def attempt(key: str):
        barrier.wait(timeout=10)
        return command(
            client,
            path,
            headers["supervisor"],
            key,
            {
                "expected_version": 1,
                "priority": "HIGH",
            },
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        first, replay, competing = list(
            pool.map(attempt, ["same-key", "same-key", "different-key"])
        )
    assert sorted([first.status_code, replay.status_code]) in ([201, 201], [409, 409])
    assert competing.status_code == (409 if first.status_code == 201 else 201)
    if first.status_code == 201:
        assert first.json() == replay.json()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(WorkOrder)) == 1


def test_repair_attempts_corrections_and_history(workflow):
    client, engine, headers, ids, asset_id = workflow
    report = report_fault(client, headers["operator"], asset_id).json()
    order = command(
        client,
        f"fault-reports/{report['id']}/work-order",
        headers["supervisor"],
        "convert",
        {"expected_version": 1, "priority": "HIGH"},
    ).json()
    path = f"work-orders/{order['id']}"
    history_path = f"{path}/history?page_size=100"

    def change(action, role, version, key=None, **data):
        return command(
            client,
            f"{path}/{action}",
            headers[role],
            key or action,
            {
                "expected_version": version,
                **data,
            },
        )

    assert (
        change(
            "assignment",
            "supervisor",
            1,
            technician_id=ids["tech"],
            due_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            reason="Inspect pump",
        ).status_code
        == 200
    )
    assert (
        change("start", "tech", 2, note="Opened inspection record").status_code == 200
    )
    assert (
        change("pause-for-parts", "tech", 3, reason="Awaiting bearing").status_code
        == 200
    )
    assert change("resume", "tech", 4, note="Bearing delivered").status_code == 200
    assert change("notes", "tech", 5, kind="PROGRESS", text=" ").status_code == 422
    part = {
        "part_code": "BRG",
        "description": "Bearing",
        "quantity": "2",
        "unit": "each",
    }
    assert change("parts-used", "tech", 5, **{**part, "quantity": 0}).status_code == 422
    assert (
        change("parts-used", "tech", 5, **{**part, "quantity": -1}).status_code == 422
    )

    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE FUNCTION test_reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.action = 'ORDER_PARTS_USED' THEN
                    RAISE EXCEPTION 'test failure';
                END IF;
                RETURN NEW;
            END; $$
        """)
        )
        connection.execute(
            text("""
            CREATE TRIGGER test_reject_audit BEFORE INSERT ON audit_events
            FOR EACH ROW EXECUTE FUNCTION test_reject_audit()
        """)
        )
    try:
        failed = change("parts-used", "tech", 5, **part)
        assert failed.status_code == 500
        assert "test failure" not in failed.text
        read = client.get(path, headers=headers["tech"]).json()
        assert read["version"] == 5 and read["totals"]["parts"] == []
        history = client.get(history_path, headers=headers["tech"])
        assert history.status_code == 200, history.text
        assert all(
            event["action"] != "ORDER_PARTS_USED" for event in history.json()["items"]
        )
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TRIGGER test_reject_audit ON audit_events"))
            connection.execute(text("DROP FUNCTION test_reject_audit()"))

    barrier = Barrier(2)

    def add_part(_):
        barrier.wait(timeout=10)
        return change("parts-used", "tech", 5, **part)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, replay = list(pool.map(add_part, range(2)))
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    labour = {"minutes": 45, "work_date": "2026-11-20", "description": "Inspection"}
    assert change("labour", "tech", 6, **labour).status_code == 200
    history = client.get(history_path, headers=headers["supervisor"]).json()["items"]
    part_ids = [event["id"] for event in history if event["action"] == "PART_RECORDED"]
    assert len(part_ids) == 1
    labour_id = next(
        event["id"] for event in history if event["action"] == "LABOUR_RECORDED"
    )
    assert (
        change(
            "corrections",
            "tech",
            7,
            "part-fix",
            entry_type="part",
            entry_id=part_ids[0],
            reason="Count reconciled",
            replacement={**part, "quantity": "1.25"},
        ).status_code
        == 200
    )
    assert (
        change(
            "corrections",
            "tech",
            8,
            "labour-fix",
            entry_type="labour",
            entry_id=labour_id,
            reason="Duration corrected",
            replacement={**labour, "minutes": 30},
        ).status_code
        == 200
    )
    totals = client.get(path, headers=headers["tech"]).json()["totals"]
    assert totals == {
        "labour_minutes": 30,
        "parts": [{"part_code": "BRG", "unit": "each", "quantity": "1.2500"}],
    }
    assert client.get(history_path).status_code == 401
    assert client.get(history_path, headers=headers["other"]).status_code == 404
    malformed = {
        "asset_id": asset_id,
        "title": "Invalid timestamp",
        "symptoms": "Fictional symptoms",
        "observed_at": "2026-11-20T12:00:00",
        "suggested_priority": "LOW",
    }
    assert (
        command(
            client, "fault-reports", headers["operator"], "bad-time", malformed
        ).status_code
        == 422
    )

    evidence = {
        "diagnosis": "Bearing wear",
        "repair_summary": "Replaced bearing",
        "test_results": "Test data recorded",
        "external_reference": "FICTIONAL-001",
    }
    assert (
        change(
            "submit-for-verification", "tech", 9, diagnosis="Only diagnosis"
        ).status_code
        == 422
    )
    submitted = change("submit-for-verification", "tech", 9, **evidence)
    assert submitted.json()["status"] == "AWAITING_VERIFICATION"
    assert (
        client.patch(
            f"users/{ids['tech']}",
            headers=headers["admin"],
            json={
                "expected_version": 1,
                "roles": ["TECHNICIAN", "SUPERVISOR"],
            },
        ).status_code
        == 200
    )
    denied = change("verification", "tech", 10, decision="ACCEPT", notes="Self-review")
    assert (
        denied.status_code == 403
        and denied.json()["error"]["code"] == "SELF_VERIFICATION"
    )
    rejected = change(
        "verification", "supervisor", 10, "reject", decision="REJECT", notes="Retest"
    )
    assert rejected.json()["status"] == "IN_PROGRESS"
    account_history = client.get(
        f"users/{ids['tech']}/history", headers=headers["admin"]
    )
    assert account_history.status_code == 200
    assert {event["action"] for event in account_history.json()["items"]} == {
        "USER_CREATED",
        "USER_UPDATED",
    }
    assert (
        client.get(
            f"users/{ids['tech']}/history", headers=headers["supervisor"]
        ).status_code
        == 403
    )
    assert (
        change(
            "assignment",
            "supervisor",
            11,
            "reassign-repair",
            technician_id=ids["other"],
            due_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            reason="Handover",
        ).status_code
        == 200
    )
    assert (
        change(
            "notes", "tech", 12, "old-assignee", kind="TEST", text="Late note"
        ).status_code
        == 404
    )
    assert (
        change("notes", "other", 12, "retest", kind="TEST", text="Retested").status_code
        == 200
    )
    assert (
        change(
            "submit-for-verification", "other", 13, "resubmit", **evidence
        ).status_code
        == 200
    )
    historic_denial = change(
        "verification",
        "tech",
        14,
        "historic-verifier",
        decision="ACCEPT",
        notes="Prior assignee",
    )
    assert historic_denial.json()["error"]["code"] == "SELF_VERIFICATION"
    accepted = change(
        "verification", "supervisor", 14, "accept", decision="ACCEPT", notes="Reviewed"
    )
    assert accepted.json()["status"] == "CLOSED"
    assert (
        change(
            "notes", "other", 15, "closed-note", kind="PROGRESS", text="Late note"
        ).status_code
        == 409
    )
    assert (
        client.get(f"assets/{asset_id}", headers=headers["operator"]).json()[
            "lifecycle"
        ]
        == "ACTIVE"
    )
    summary = client.get(
        "reports/maintenance-summary", headers=headers["supervisor"]
    ).json()
    assert summary["by_status"]["CLOSED"] == 1 and summary["overdue_count"] == 0
    assert summary["average_closure_seconds"] >= 0
    assert (
        client.get(
            "reports/maintenance-summary", headers=headers["operator"]
        ).status_code
        == 403
    )
    first_page = client.get(
        f"{path}/history?page_size=2", headers=headers["other"]
    ).json()
    second_page = client.get(
        f"{path}/history?page_size=2&page=2", headers=headers["other"]
    ).json()
    assert (
        len({event["id"] for event in first_page["items"] + second_page["items"]}) == 4
    )

    with TestClient(
        create_app(client.app.state.settings), base_url="http://localhost/api/v1/"
    ) as restarted:
        history = restarted.get(
            f"assets/{asset_id}/maintenance-history?page_size=100",
            headers=headers["supervisor"],
        ).json()["items"]
        assert {
            event["details"]["decision"]
            for event in history
            if event["action"] == "VERIFICATION_RECORDED"
        } == {"ACCEPT", "REJECT"}
        assert (
            len([event for event in history if event["action"] == "PART_RECORDED"]) == 2
        )
