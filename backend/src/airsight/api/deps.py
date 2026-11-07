"""What every route can ask for: a database connection and the current time."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection

from airsight.core.db import get_engine


def get_connection() -> Iterator[Connection]:
    with get_engine().connect() as connection:
        yield connection


def get_now() -> datetime:
    """The current time. A dependency so tests can freeze the clock."""
    return datetime.now(UTC)


DbConnection = Annotated[Connection, Depends(get_connection)]
Now = Annotated[datetime, Depends(get_now)]
