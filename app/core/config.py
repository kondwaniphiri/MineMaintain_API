from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )

    database_url: SecretStr | None = None
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "minemaintain"
    db_user: str = "minemaintain"
    db_password: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw_url = value.get_secret_value().strip()
        try:
            url = make_url(raw_url)
        except (ArgumentError, ValueError, TypeError):
            raise ValueError("Paste a valid PostgreSQL connection URL") from None
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError(
                "Use a postgres://, postgresql://, or postgresql+psycopg:// URL"
            )
        return SecretStr(raw_url)

    def connection_url(self) -> URL:
        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value()).set(
                drivername="postgresql+psycopg"
            )
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value() if self.db_password else None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


class Settings(DatabaseSettings):
    jwt_secret: SecretStr
    jwt_issuer: str = Field(default="minemaintain-api", min_length=1)
    jwt_audience: str = Field(default="minemaintain-client", min_length=1)
    access_token_minutes: int = Field(default=15, ge=1, le=15)
    environment: Literal["local", "test", "production"] = "local"

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret.encode()) < 32 or not secret.strip():
            raise ValueError("JWT_SECRET must contain at least 32 bytes")
        return value
