from typing import Annotated

from pydantic import AfterValidator, EmailStr, Field, SecretStr

from app.db.models import Role
from app.schemas.auth import Identity
from app.schemas.workflow import Label, Versioned, Write


def normalize_email(email: str) -> str:
    email = email.lower()
    if len(email) > 254:
        raise ValueError("Email must contain at most 254 characters")
    return email


def unique_roles(roles: list[Role]) -> list[Role]:
    if len(roles) != len(set(roles)):
        raise ValueError("Roles must be unique")
    return roles


Email = Annotated[EmailStr, AfterValidator(normalize_email)]
Roles = Annotated[
    list[Role], Field(min_length=1, max_length=4), AfterValidator(unique_roles)
]


class UserCreate(Write):
    email: Email
    full_name: Label
    password: SecretStr = Field(min_length=12, max_length=1024)
    roles: Roles


class UserPatch(Versioned):
    full_name: Label | None = None
    roles: Roles | None = None
    is_active: bool | None = None


class Account(Identity):
    is_active: bool
    version: int
