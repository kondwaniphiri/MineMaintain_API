from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.errors import ApiError
from app.core.security import issue_token, password_hash, token_subject
from app.db.models import Role, User
from app.db.session import DbSession
from app.schemas.auth import Identity, TokenRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["authentication"])
Bearer = Annotated[
    HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
]


def unauthorized(message: str) -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message, {"WWW-Authenticate": "Bearer"})


def get_current_user(request: Request, credentials: Bearer, session: DbSession) -> User:
    if credentials is None:
        raise unauthorized("Valid access token required")
    try:
        user_id = token_subject(credentials.credentials, request.app.state.settings)
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise unauthorized("Valid access token required") from None

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized("Valid access token required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    def check_roles(user: CurrentUser) -> User:
        if not set(roles).intersection(user.roles):
            raise ApiError(403, "FORBIDDEN", "Insufficient permissions")
        return user

    return check_roles


@router.post("/token")
def login(
    data: TokenRequest, request: Request, response: Response, session: DbSession
) -> TokenResponse:
    email = data.email.strip().lower()
    client_ip = request.client.host if request.client else "unknown"
    retry_after = request.app.state.login_limits.consume(email, client_ip)
    if retry_after:
        raise ApiError(
            429,
            "TOO_MANY_ATTEMPTS",
            "Too many login attempts",
            {"Retry-After": str(retry_after)},
        )

    slots = request.app.state.login_slots
    if not slots.acquire(blocking=False):
        raise ApiError(
            503, "LOGIN_BUSY", "Login is temporarily busy", {"Retry-After": "1"}
        )
    try:
        user = (
            session.scalar(select(User).where(User.email == email))
            if "\x00" not in email
            else None
        )
        stored_hash = (
            user.password_hash
            if user and user.is_active
            else request.app.state.dummy_hash
        )
        valid = password_hash.verify(data.password.get_secret_value(), stored_hash)
    finally:
        slots.release()
    if user is None or not user.is_active or not valid:
        raise unauthorized("Invalid email or password")

    settings = request.app.state.settings
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=issue_token(user.id, settings),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me")
def me(user: CurrentUser) -> Identity:
    return Identity.model_validate(user)
