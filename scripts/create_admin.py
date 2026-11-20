from argparse import ArgumentParser
from getpass import getpass

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import DatabaseSettings
from app.core.security import password_hash
from app.db.models import Role, User
from app.db.session import build_engine


def main() -> None:
    parser = ArgumentParser(description="Create an administrator account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        email = TypeAdapter(EmailStr).validate_python(args.email.strip()).lower()
    except ValidationError:
        parser.error("Enter a valid email address")
    full_name = args.name.strip()
    if len(email) > 254 or not 1 <= len(full_name) <= 160:
        parser.error("Email or name has an invalid length")

    password = getpass("Password (at least 12 characters): ")
    if not 12 <= len(password) <= 1024 or not password.strip():
        parser.error("Enter a password between 12 and 1024 characters")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")

    engine = build_engine(DatabaseSettings())
    try:
        with Session(engine) as session, session.begin():
            session.add(
                User(
                    email=email,
                    full_name=full_name,
                    password_hash=password_hash.hash(password),
                    roles=[Role.ADMINISTRATOR],
                )
            )
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            parser.exit(1, "An account with this email already exists.\n")
        raise
    finally:
        engine.dispose()
    print("Administrator created.")


if __name__ == "__main__":
    main()
