from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import DatabaseSettings


def build_engine(settings: DatabaseSettings):
    return create_engine(
        settings.connection_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]
