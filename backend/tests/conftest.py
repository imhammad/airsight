import time
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from airsight.core.config import Settings
from airsight.core.db import upgrade_database

TEST_DATABASE = "airsight_test"


def drop_test_database(admin: Engine) -> None:
    """Drop the test database, retrying while TimescaleDB's scheduler lets go of it."""
    for attempt in range(5):
        try:
            with admin.connect() as connection:
                connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)"))
            return
        except OperationalError:
            if attempt == 4:
                raise
            time.sleep(1)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """A fresh test database with every migration applied, dropped after the test run."""
    server_url = make_url(Settings(_env_file=None).database_url)
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        pytest.fail(
            f"Cannot reach PostgreSQL at {server_url.render_as_string()}. "
            "Start it with: docker compose up -d --wait db"
        )
    drop_test_database(admin)
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {TEST_DATABASE}"))

    test_url = server_url.set(database=TEST_DATABASE)
    upgrade_database(test_url.render_as_string(hide_password=False))
    test_engine = create_engine(test_url)

    yield test_engine

    # TimescaleDB runs a background scheduler in every database that has the extension.
    # It can reconnect while the database is being dropped, so stop it first.
    with test_engine.connect() as connection:
        connection.execute(text("SELECT _timescaledb_functions.stop_background_workers()"))
    test_engine.dispose()
    drop_test_database(admin)
    admin.dispose()
