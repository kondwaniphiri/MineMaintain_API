from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def issue_token(user_id: UUID, settings: Settings) -> str:
    issued = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": issued,
            "exp": issued + timedelta(minutes=settings.access_token_minutes),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )


def token_subject(token: str, settings: Settings) -> UUID:
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[ALGORITHM],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "iss", "aud", "iat", "exp"]},
    )
    return UUID(claims["sub"])
