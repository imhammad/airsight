"""Loading steps shared by the backfill command and the live ingestion job."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import Engine, text

from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.open_meteo import Point, WeatherHour
from airsight.ingestion.purpleair import LowcostReading, PointsBudget, Sensor
from airsight.ingestion.regions import BAY_AREA, BoundingBox


class ReferenceSource(Protocol):
    def hourly_pm25(
        self, area: BoundingBox, start: datetime, end: datetime
    ) -> list[ReferenceReading]: ...


class LowcostSource(Protocol):
    budget: PointsBudget

    def sensors(self, area: BoundingBox, max_sensors: int = ...) -> list[Sensor]: ...

    def hourly_readings(
        self, sensor_index: int, start: datetime, end: datetime
    ) -> list[LowcostReading]: ...


class WeatherSource(Protocol):
    def recent(
        self, points: Sequence[Point], past_days: int = ...
    ) -> dict[Point, list[WeatherHour]]: ...


def load_reference(
    engine: Engine, reference: ReferenceSource, start: datetime, end: datetime
) -> int:
    """Official monitor readings for [start, end): one day per request and per transaction."""
    rows = 0
    day = start
    while day < end:
        day_end = min(day + timedelta(days=1), end)
        # AirNow's end hour is inclusive, ours is exclusive
        readings = reference.hourly_pm25(BAY_AREA, day, day_end - timedelta(hours=1))
        with engine.begin() as connection:
            ids = store.upsert_reference_stations(connection, readings)
            rows += store.upsert_reference_readings(connection, readings, ids)
        day = day_end
    return rows


def load_lowcost(
    engine: Engine,
    lowcost: LowcostSource,
    sensor_index: int,
    sensor_id: int,
    start: datetime,
    end: datetime,
) -> int:
    """Hourly readings of one low-cost sensor for [start, end), in one transaction."""
    readings = lowcost.hourly_readings(sensor_index, start, end)
    with engine.begin() as connection:
        return store.upsert_lowcost_readings(connection, readings, {sensor_index: sensor_id})


def load_weather(engine: Engine, weather: WeatherSource, start: datetime, end: datetime) -> int:
    """Observed weather for [start, end) in every cell in use. Forecast hours are never stored."""
    rows = 0
    with engine.begin() as connection:
        cells = store.weather_cells_in_use(connection)
        points = {Point(*map(float, cell.split(","))): cell for cell in cells}
        past_days = (datetime.now(UTC) - start).days + 1
        for point, hours in weather.recent(list(points), past_days=past_days).items():
            observed = [h for h in hours if start <= h.time < end]
            rows += store.upsert_weather(connection, points[point], observed)
    return rows


def refresh_hourly(engine: Engine, start: datetime, end: datetime) -> None:
    """Recompute the hourly averages for [start, end). Can't run inside a transaction."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(
            text("CALL refresh_continuous_aggregate('lowcost_hourly', :start, :end)"),
            {"start": start, "end": end},
        )
