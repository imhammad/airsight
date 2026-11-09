from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from airsight.api import queries
from airsight.api.deps import DbConnection, Now
from airsight.api.problems import responses
from airsight.api.schemas import LatestPage, NearbyPage

router = APIRouter(tags=["readings"])


@router.get("/readings/latest", response_model=LatestPage, responses=responses(400))
def latest(
    connection: DbConnection,
    now: Now,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    cursor: Annotated[str | None, Query(description="next_cursor of the previous page")] = None,
) -> LatestPage:
    """Every sensor we serve with its latest reading, for a map. Excluded ones have none."""
    try:
        page, next_cursor = queries.list_latest(connection, cursor, limit, now)
    except queries.InvalidCursorError:
        raise HTTPException(status_code=400, detail="cursor is not one this API returned") from None
    return LatestPage(data=page, next_cursor=next_cursor)


@router.get("/readings/nearest", response_model=NearbyPage)
def nearest(
    connection: DbConnection,
    now: Now,
    lat: Annotated[float, Query(ge=-90, le=90, description="Latitude in degrees")],
    lon: Annotated[float, Query(ge=-180, le=180, description="Longitude in degrees")],
    radius_km: Annotated[float, Query(gt=0, le=50)] = 10,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> NearbyPage:
    """Latest corrected readings of the closest healthy sensors, nearest first."""
    data = queries.nearest(connection, lat, lon, radius_km, limit, now)
    return NearbyPage(data=data, next_cursor=None)
