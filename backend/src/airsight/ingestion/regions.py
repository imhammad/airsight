"""Geographic areas we collect data for."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    west: float
    south: float
    east: float
    north: float


# Training region (ADR 0001). The same box was used for the data coverage check.
BAY_AREA = BoundingBox(west=-123.0, south=37.2, east=-121.6, north=38.3)
