"""Geographic areas we collect data for."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    west: float
    south: float
    east: float
    north: float


# Training region (ADR 0001). The same box was used for the data coverage check.
BAY_AREA = BoundingBox(west=-123.0, south=37.2, east=-121.6, north=38.3)


def around(latitude: float, longitude: float, km: float) -> BoundingBox:
    """A box reaching at least `km` from a point in every direction."""
    lat_step = km / 111.0  # one degree of latitude is about 111 km
    lon_step = km / (111.0 * math.cos(math.radians(latitude)))
    return BoundingBox(
        west=longitude - lon_step,
        south=latitude - lat_step,
        east=longitude + lon_step,
        north=latitude + lat_step,
    )


def weather_cell(latitude: float, longitude: float) -> str:
    """The 0.1-degree weather grid cell a point falls in, written as 'lat,lon' of its centre."""
    return f"{round(latitude, 1):.1f},{round(longitude, 1):.1f}"
