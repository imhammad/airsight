from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime

from airsight.api import queries
from airsight.api.deps import DbConnection, Now
from airsight.api.problems import responses
from airsight.api.schemas import ReadingPage, SensorDetail, SensorPage

router = APIRouter(tags=["sensors"])

MAX_HISTORY = timedelta(days=31)


@router.get("/sensors", response_model=SensorPage, responses=responses(400))
def list_sensors(
    connection: DbConnection,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(description="next_cursor of the previous page")] = None,
) -> SensorPage:
    """Every sensor we serve, including excluded ones, in a stable order."""
    try:
        page, next_cursor = queries.list_sensors(connection, cursor, limit)
    except queries.InvalidCursorError:
        raise HTTPException(status_code=400, detail="cursor is not one this API returned") from None
    return SensorPage(data=page, next_cursor=next_cursor)


@router.get("/sensors/{sensor_id}", response_model=SensorDetail, responses=responses(404))
def get_sensor(sensor_id: str, connection: DbConnection, now: Now) -> SensorDetail:
    """One sensor and its latest corrected reading."""
    sensor = queries.get_sensor(connection, sensor_id, now)
    if sensor is None:
        raise HTTPException(status_code=404, detail=f"No sensor with id {sensor_id}")
    return sensor


@router.get("/sensors/{sensor_id}/history", response_model=ReadingPage, responses=responses(404))
def get_history(
    sensor_id: str,
    connection: DbConnection,
    now: Now,
    start: Annotated[AwareDatetime, Query(description="Inclusive, with a time zone, e.g. ...Z")],
    end: Annotated[AwareDatetime, Query(description="Exclusive, with a time zone")],
) -> ReadingPage:
    """Hourly corrected readings between start and end, oldest first (at most 31 days)."""
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if end - start > MAX_HISTORY:
        raise HTTPException(status_code=422, detail="at most 31 days per request")
    if queries.get_sensor(connection, sensor_id, now) is None:
        raise HTTPException(status_code=404, detail=f"No sensor with id {sensor_id}")
    return ReadingPage(
        data=queries.history(connection, sensor_id, start, end, now), next_cursor=None
    )
