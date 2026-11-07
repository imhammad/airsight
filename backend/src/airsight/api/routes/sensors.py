from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from airsight.api import queries
from airsight.api.deps import DbConnection, Now
from airsight.api.schemas import SensorDetail, SensorPage

router = APIRouter(tags=["sensors"])


@router.get("/sensors", response_model=SensorPage)
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


@router.get("/sensors/{sensor_id}", response_model=SensorDetail)
def get_sensor(sensor_id: str, connection: DbConnection, now: Now) -> SensorDetail:
    """One sensor and its latest corrected reading."""
    sensor = queries.get_sensor(connection, sensor_id, now)
    if sensor is None:
        raise HTTPException(status_code=404, detail=f"No sensor with id {sensor_id}")
    return sensor
