"""What routes can ask for: a database connection, the current time and the champion model."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import Connection

from airsight.api.champion import load_champion_info
from airsight.api.schemas import ModelInfo
from airsight.core.db import get_engine


def get_connection() -> Iterator[Connection]:
    with get_engine().connect() as connection:
        yield connection


def get_now() -> datetime:
    """The current time. A dependency so tests can freeze the clock."""
    return datetime.now(UTC)


def get_champion() -> ModelInfo:
    """The champion's description. 503 until a model has been promoted (ADR 0008)."""
    champion = load_champion_info()
    if champion is None:
        raise HTTPException(status_code=503, detail="No model has been promoted yet")
    return champion


DbConnection = Annotated[Connection, Depends(get_connection)]
Now = Annotated[datetime, Depends(get_now)]
Champion = Annotated[ModelInfo, Depends(get_champion)]
