from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from airsight.core.config import Settings
from airsight.core.db import upgrade_database

TEST_DATABASE = "airsight_test"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """A fresh test database with every migration applied, dropped after the test run."""
    server_url = make_url(Settings(_env_file=None).database_url)
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {TEST_DATABASE}"))
    except OperationalError:
        pytest.fail(
            f"Cannot reach PostgreSQL at {server_url.render_as_string()}. "
            "Start it with: docker compose up -d --wait db"
        )

    test_url = server_url.set(database=TEST_DATABASE)
    upgrade_database(test_url.render_as_string(hide_password=False))
    test_engine = create_engine(test_url)

    yield test_engine

    test_engine.dispose()
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE {TEST_DATABASE} WITH (FORCE)"))
    admin.dispose()
