from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import uuid4

import jwt
import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.auth import require_roles
from app.core.errors import ApiError
from app.core.security import password_hash, token_subject
from app.db.models import Role, User
from app.main import create_app
from app.services.login_limits import LoginLimits


def test_live_and_ready_when_database_is_unavailable():
    app = create_app(make_settings("postgresql+psycopg://unused@127.0.0.1:1/unused"))
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_does_not_echo_request_data():
    app = create_app(make_settings("postgresql+psycopg://unused@127.0.0.1:1/unused"))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/token", json={"sensitive-key": "sensitive-value"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "sensitive" not in response.text


def test_role_checks_require_a_matching_role():
    supervisor_only = require_roles(Role.SUPERVISOR)
    user = User(roles=[Role.ADMINISTRATOR])
    with pytest.raises(ApiError) as error:
        supervisor_only(user)
    assert error.value.status_code == 403
    user.roles.append(Role.SUPERVISOR)
    assert supervisor_only(user) is user


def test_login_limits_by_account_and_ip():
    limiter = LoginLimits(capacity=100)
    for _ in range(5):
        assert limiter.consume("one@example.com", "one-ip") == 0
    assert limiter.consume("one@example.com", "other-ip") > 0
    for _ in range(25):
        limiter.consume("one@example.com", "one-ip")
    assert limiter.consume("two@example.com", "one-ip") > 0
    assert limiter.consume("two@example.com", "other-ip") == 0


@pytest.mark.parametrize(
    ("claim", "value", "algorithm"),
    [
        ("iss", "other-issuer", "HS256"),
        ("aud", "other-audience", "HS256"),
        ("exp", datetime.now(UTC) - timedelta(minutes=1), "HS256"),
        ("sub", str(uuid4()), "HS384"),
    ],
)
def test_token_rejects_invalid_claims_and_algorithm(claim, value, algorithm):
    settings = make_settings("postgresql+psycopg://unused@127.0.0.1:1/unused")
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now - timedelta(minutes=2),
        "exp": now + timedelta(minutes=1),
        claim: value,
    }
    token = jwt.encode(
        claims, settings.jwt_secret.get_secret_value(), algorithm=algorithm
    )
    with pytest.raises(jwt.InvalidTokenError):
        token_subject(token, settings)


def test_login_and_current_identity(database):
    settings, engine = database
    password = token_urlsafe()
    user_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            User(
                id=user_id,
                email="operator@example.com",
                full_name="Fictional Operator",
                password_hash=password_hash.hash(password),
                roles=[Role.OPERATOR],
            )
        )

    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401
        payload = {"email": " Operator@Example.com ", "password": password}
        response = client.post("/api/v1/auth/token", json=payload)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["expires_in"] == settings.access_token_minutes * 60
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).json() == {
            "id": str(user_id),
            "email": "operator@example.com",
            "full_name": "Fictional Operator",
            "roles": ["OPERATOR"],
        }

        with Session(engine) as session, session.begin():
            session.get(User, user_id).roles = [Role.TECHNICIAN, Role.SUPERVISOR]
        assert client.get("/api/v1/auth/me", headers=headers).json()["roles"] == [
            "TECHNICIAN",
            "SUPERVISOR",
        ]

        with Session(engine) as session, session.begin():
            session.get(User, user_id).is_active = False
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        disabled = client.post("/api/v1/auth/token", json=payload)
        payload["email"] = "unknown@example.com"
        unknown = client.post("/api/v1/auth/token", json=payload)
        assert disabled.status_code == unknown.status_code == 401
        assert disabled.json()["error"] == unknown.json()["error"]
