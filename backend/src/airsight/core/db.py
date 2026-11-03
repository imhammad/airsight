"""Database engine and migrations."""

from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

from airsight.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def upgrade_database(database_url: str) -> None:
    """Apply every migration that hasn't run yet."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Alembic's config treats % specially, so a % in a password must be doubled
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
