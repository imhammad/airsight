from typing import Annotated

from fastapi import APIRouter, Query

from airsight.api import queries
from airsight.api.deps import DbConnection, Now
from airsight.api.schemas import NearbyPage

router = APIRouter(tags=["readings"])


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
