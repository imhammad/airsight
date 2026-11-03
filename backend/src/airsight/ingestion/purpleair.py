"""PurpleAir client: low-cost sensor readings, with a guard on the points every call costs."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from pydantic import BaseModel, SecretStr

from airsight.ingestion.http_client import get_json
from airsight.ingestion.regions import BoundingBox

BASE_URL = "https://api.purpleair.com/v1"

# From the PurpleAir Develop portal, Billing > Pricing (checked 2026-11-03).
# A call costs its request price plus, for every row returned, the sum of its fields' prices.
REQUEST_POINTS = {"sensors": 5, "history": 2}
FIELD_POINTS = {
    "sensor_index": 0,
    "time_stamp": 0,
    "name": 1,
    "latitude": 1,
    "longitude": 1,
    "last_seen": 1,
    "pm2.5_cf_1_a": 1,
    "pm2.5_cf_1_b": 1,
    "humidity": 2,
}
SENSOR_FIELDS = ("name", "latitude", "longitude", "last_seen")
# Temperature is left out on purpose: Open-Meteo provides it for free (ADR 0006)
READING_FIELDS = ("pm2.5_cf_1_a", "pm2.5_cf_1_b", "humidity")
# The longest time span PurpleAir returns in one history request with hourly averages
MAX_HISTORY_SPAN = timedelta(days=14)


class PointsBudgetExceededError(Exception):
    """A call would spend more points than this run is allowed to."""


class PointsBudget:
    """Counts the points a run spends and refuses any call that could go over the limit."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0

    def check(self, worst_case: int) -> None:
        if self.spent + worst_case > self.limit:
            raise PointsBudgetExceededError(
                f"Call could cost {worst_case} points; {self.spent} of {self.limit} already spent"
            )

    def charge(self, points: int) -> None:
        self.spent += points


def call_cost(request: str, fields: Sequence[str], rows: int) -> int:
    return REQUEST_POINTS[request] + rows * sum(FIELD_POINTS[f] for f in fields)


@dataclass(frozen=True)
class Sensor:
    sensor_index: int
    name: str
    latitude: float
    longitude: float
    last_seen: datetime


@dataclass(frozen=True)
class LowcostReading:
    sensor_index: int
    time: datetime  # start of the hour, UTC
    pm25_a: float | None  # µg/m³, laser counter A, CF=1
    pm25_b: float | None  # µg/m³, laser counter B, CF=1
    humidity: float | None  # %, inside the sensor housing


class _Table(BaseModel):
    """PurpleAir sends rows as lists, with a separate list naming the columns."""

    fields: list[str]
    data: list[list[Any]]

    def records(self) -> list[dict[str, Any]]:
        return [dict(zip(self.fields, row, strict=True)) for row in self.data]


class PurpleAirClient:
    def __init__(self, client: httpx2.Client, api_key: SecretStr, budget: PointsBudget) -> None:
        self._client = client
        self._headers = {"X-API-Key": api_key.get_secret_value()}
        self.budget = budget

    def sensors(self, area: BoundingBox, max_sensors: int = 3000) -> list[Sensor]:
        """Outdoor sensors in the area that reported during the last hour."""
        self.budget.check(call_cost("sensors", SENSOR_FIELDS, max_sensors))
        table = self._get(
            "/sensors",
            {
                "fields": ",".join(SENSOR_FIELDS),
                "location_type": 0,  # outdoor only
                "max_age": 3600,
                "nwlng": area.west,
                "nwlat": area.north,
                "selng": area.east,
                "selat": area.south,
            },
        )
        self.budget.charge(call_cost("sensors", SENSOR_FIELDS, len(table.data)))
        return [
            Sensor(
                sensor_index=r["sensor_index"],
                name=r["name"],
                latitude=r["latitude"],
                longitude=r["longitude"],
                last_seen=datetime.fromtimestamp(r["last_seen"], UTC),
            )
            for r in table.records()
            if r["latitude"] is not None and r["longitude"] is not None
        ]

    def hourly_readings(
        self, sensor_index: int, start: datetime, end: datetime
    ) -> list[LowcostReading]:
        """Hourly averages for one sensor from start (inclusive) to end (exclusive)."""
        readings: list[LowcostReading] = []
        window_start = start
        while window_start < end:
            window_end = min(window_start + MAX_HISTORY_SPAN, end)
            readings += self._history_window(sensor_index, window_start, window_end)
            window_start = window_end
        return sorted(readings, key=lambda r: r.time)

    def _history_window(
        self, sensor_index: int, start: datetime, end: datetime
    ) -> list[LowcostReading]:
        hours = int((end - start) / timedelta(hours=1)) + 1
        self.budget.check(call_cost("history", READING_FIELDS, hours))
        table = self._get(
            f"/sensors/{sensor_index}/history",
            {
                "fields": ",".join(READING_FIELDS),
                "average": 60,
                "start_timestamp": int(start.timestamp()),
                "end_timestamp": int(end.timestamp()),
            },
        )
        self.budget.charge(call_cost("history", READING_FIELDS, len(table.data)))
        return [
            LowcostReading(
                sensor_index=sensor_index,
                time=datetime.fromtimestamp(r["time_stamp"], UTC),
                pm25_a=r["pm2.5_cf_1_a"],
                pm25_b=r["pm2.5_cf_1_b"],
                humidity=r["humidity"],
            )
            for r in table.records()
        ]

    def _get(self, path: str, params: dict[str, str | int | float]) -> _Table:
        body = get_json(self._client, BASE_URL + path, params=params, headers=self._headers)
        return _Table.model_validate(body)
