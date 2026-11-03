"""EPA AirNow client: hourly PM2.5 from official monitors, our ground truth."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx2
from pydantic import BaseModel, SecretStr

from airsight.ingestion.http_client import get_json
from airsight.ingestion.regions import BoundingBox

DATA_URL = "https://www.airnowapi.org/aq/data/"
# AirNow marks a missing measurement with -999
MISSING = -999.0


class AirNowError(Exception):
    """A failed AirNow request. The message never contains the API key."""


@dataclass(frozen=True)
class ReferenceReading:
    station_id: str  # the monitor's full AQS code, stable across requests
    site_name: str
    latitude: float
    longitude: float
    time: datetime  # start of the hour, UTC
    pm25: float  # raw hourly concentration, µg/m³


class _Observation(BaseModel):
    Latitude: float
    Longitude: float
    UTC: str
    Parameter: str
    RawConcentration: float
    SiteName: str
    FullAQSCode: str


class AirNowClient:
    def __init__(self, client: httpx2.Client, api_key: SecretStr) -> None:
        self._client = client
        self._api_key = api_key

    def hourly_pm25(
        self, area: BoundingBox, start: datetime, end: datetime
    ) -> list[ReferenceReading]:
        """Hourly PM2.5 for every monitor in the area, from start to end (UTC, inclusive)."""
        params: dict[str, str | int | float] = {
            "startDate": _hour(start),
            "endDate": _hour(end),
            "parameters": "PM25",
            "BBOX": f"{area.west},{area.south},{area.east},{area.north}",
            "dataType": "C",
            "format": "application/json",
            "verbose": 1,
            "monitorType": 0,
            # Value is the NowCast (a smoothed multi-hour average); we want the measured hour
            "includerawconcentrations": 1,
            "API_KEY": self._api_key.get_secret_value(),
        }
        try:
            body: Any = get_json(self._client, DATA_URL, params=params)
        except httpx2.HTTPStatusError as error:
            # The original error's message includes the full URL, key included
            raise AirNowError(f"AirNow returned HTTP {error.response.status_code}") from None
        except httpx2.HTTPError as error:
            raise AirNowError(f"AirNow request failed: {type(error).__name__}") from None

        readings = []
        for row in body:
            observation = _Observation.model_validate(row)
            if observation.Parameter != "PM2.5" or observation.RawConcentration <= MISSING:
                continue
            readings.append(
                ReferenceReading(
                    station_id=observation.FullAQSCode,
                    site_name=observation.SiteName,
                    latitude=observation.Latitude,
                    longitude=observation.Longitude,
                    time=datetime.fromisoformat(observation.UTC).replace(tzinfo=UTC),
                    pm25=observation.RawConcentration,
                )
            )
        return readings


def _hour(moment: datetime) -> str:
    """AirNow wants UTC hours written as 2026-11-01T12."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H")
