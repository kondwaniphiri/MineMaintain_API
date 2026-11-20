from alembic import context
from app.core.config import DatabaseSettings
from app.db.metadata import Base
from app.db.session import build_engine

settings = DatabaseSettings()


def run_migrations():
    if context.is_offline_mode():
        context.configure(
            url=settings.connection_url(),
            target_metadata=Base.metadata,
            literal_binds=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
