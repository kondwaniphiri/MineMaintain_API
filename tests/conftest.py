from secrets import token_urlsafe

import pytest
from alembic.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import inspect, text

from alembic import command
from app.core.config import Settings
from app.db.session import build_engine


class TestDatabaseConfig(BaseSettings):
    __test__ = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_database_url: str | None = None


def make_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        jwt_secret=token_urlsafe(48),
        environment="test",
        _env_file=None,
    )


@pytest.fixture
def database(monkeypatch):
    url = TestDatabaseConfig().test_database_url
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration checks")
    settings = make_settings(url)
    engine = build_engine(settings)
    try:
        tables = set(inspect(engine).get_table_names())
        if tables - {"alembic_version"}:
            pytest.fail("TEST_DATABASE_URL must point to an empty database")
        if "alembic_version" in tables:
            with engine.connect() as connection:
                if connection.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM alembic_version)")
                ):
                    pytest.fail("TEST_DATABASE_URL already has migrations applied")
        monkeypatch.setenv("DATABASE_URL", url)
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        try:
            command.check(config)
            yield settings, engine
        finally:
            command.downgrade(config, "base")
    finally:
        engine.dispose()
