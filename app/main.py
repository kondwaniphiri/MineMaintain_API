import json
import logging
from contextlib import asynccontextmanager
from secrets import token_urlsafe
from threading import BoundedSemaphore
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.auth import router as auth_router
from app.api.v1.equipment import router as equipment_router
from app.api.v1.faults import router as faults_router
from app.api.v1.history import router as history_router
from app.api.v1.orders import router as orders_router
from app.api.v1.repairs import router as repairs_router
from app.api.v1.reports import router as reports_router
from app.api.v1.users import router as users_router
from app.core.config import Settings
from app.core.errors import ApiError, error_response, install_error_handlers
from app.core.security import password_hash
from app.db.session import build_engine
from app.services.login_limits import LoginLimits

logger = logging.getLogger("minemaintain.requests")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings if settings is not None else Settings()
        app.state.login_limits = LoginLimits()
        app.state.login_slots = BoundedSemaphore(4)
        app.state.dummy_hash = password_hash.hash(token_urlsafe())
        engine = build_engine(app.state.settings)
        app.state.engine = engine
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Mine Equipment Maintenance API", version="0.1.0", lifespan=lifespan
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def correlate(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = perf_counter()
        failure = None
        try:
            response = await call_next(request)
        except Exception as exc:
            failure = type(exc).__name__
            response = error_response(
                request, 500, "INTERNAL_ERROR", "Unexpected server error"
            )

        response.headers["X-Request-ID"] = request.state.request_id
        route = request.scope.get("route")
        event = {
            "request_id": request.state.request_id,
            "method": request.method,
            "route": getattr(route, "path", None),
            "status": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        }
        if failure:
            event["exception_type"] = failure
        logger.log(
            logging.ERROR if response.status_code >= 500 else logging.INFO,
            json.dumps(event),
        )
        return response

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(request: Request):
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise ApiError(
                503, "DATABASE_UNAVAILABLE", "Database unavailable"
            ) from None
        return {"status": "ok"}

    for router in (
        auth_router,
        users_router,
        equipment_router,
        faults_router,
        orders_router,
        repairs_router,
        history_router,
        reports_router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
