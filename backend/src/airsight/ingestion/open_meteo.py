"""Open-Meteo client: hourly weather for a list of points. No API key needed."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx2
from pydantic import AwareDatetime, BaseModel

from airsight.ingestion.http_client import get_json

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# What the weather model forecast 24 hours before each hour (ADR 0012), archived since 2024
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
DAY_AHEAD = "_previous_day1"
HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
)


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class WeatherHour:
    time: datetime
    temperature: float | None  # °C
    relative_humidity: float | None  # %
    wind_speed: float | None  # km/h
    wind_direction: float | None  # degrees
    precipitation: float | None  # mm


class _Hourly(BaseModel):
    time: list[AwareDatetime]
    temperature_2m: list[float | None]
    relative_humidity_2m: list[float | None]
    wind_speed_10m: list[float | None]
    wind_direction_10m: list[float | None]
    precipitation: list[float | None]


class _Location(BaseModel):
    hourly: _Hourly


class OpenMeteoClient:
    def __init__(self, client: httpx2.Client) -> None:
        self._client = client

    def recent(self, points: Sequence[Point], past_days: int = 2) -> dict[Point, list[WeatherHour]]:
        """The last few days of observed weather (used by live ingestion)."""
        return self._fetch(FORECAST_URL, points, {"past_days": past_days, "forecast_days": 1})

    def history(
        self, points: Sequence[Point], start: date, end: date
    ) -> dict[Point, list[WeatherHour]]:
        """Historical weather between two dates, inclusive (used by the backfill)."""
        return self._fetch(
            ARCHIVE_URL, points, {"start_date": start.isoformat(), "end_date": end.isoformat()}
        )

    def day_ahead(
        self, points: Sequence[Point], start: date, end: date
    ) -> dict[Point, list[WeatherHour]]:
        """The forecast made 24 hours before each hour, between two dates inclusive.

        Training the air quality forecast on these, never on observed weather, keeps future
        weather out of its inputs (ADR 0012).
        """
        return self._fetch(
            PREVIOUS_RUNS_URL,
            points,
            {"start_date": start.isoformat(), "end_date": end.isoformat()},
            suffix=DAY_AHEAD,
        )

    def _fetch(
        self,
        url: str,
        points: Sequence[Point],
        extra: dict[str, str | int],
        suffix: str = "",
    ) -> dict[Point, list[WeatherHour]]:
        if not points:
            return {}
        params: dict[str, str | int | float] = {
            "latitude": ",".join(str(p.latitude) for p in points),
            "longitude": ",".join(str(p.longitude) for p in points),
            "hourly": ",".join(variable + suffix for variable in HOURLY_VARIABLES),
            "timeformat": "unixtime",  # times as UTC seconds, never local time
            **extra,
        }
        body: Any = get_json(self._client, url, params=params)
        # One point returns a single object; several return a list in the same order
        locations = body if isinstance(body, list) else [body]
        if len(locations) != len(points):
            raise ValueError(f"Asked for {len(points)} points, got {len(locations)}")
        return {
            point: _to_hours(_Location.model_validate(_without_suffix(location, suffix)).hourly)
            for point, location in zip(points, locations, strict=True)
        }


def _without_suffix(location: dict[str, Any], suffix: str) -> dict[str, Any]:
    """temperature_2m_previous_day1 becomes temperature_2m, so one parser reads every API."""
    if not suffix:
        return location
    hourly = {key.removesuffix(suffix): values for key, values in location["hourly"].items()}
    return {**location, "hourly": hourly}


def _to_hours(hourly: _Hourly) -> list[WeatherHour]:
    return [
        WeatherHour(*values)
        for values in zip(
            hourly.time,
            hourly.temperature_2m,
            hourly.relative_humidity_2m,
            hourly.wind_speed_10m,
            hourly.wind_direction_10m,
            hourly.precipitation,
            strict=True,
        )
    ]
