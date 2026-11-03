"""Alembic environment: runs migrations against the configured database."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from airsight.core.config import get_settings
from airsight.core.tables import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations() -> None:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not supported. Run migrations against a database.")

run_migrations()
