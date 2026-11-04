from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.live import LOCK_ID, lowcost_window, run_live_ingestion
from airsight.ingestion.open_meteo import Point, WeatherHour
from airsight.ingestion.purpleair import LowcostReading, PointsBudget, Sensor
from airsight.ingestion.regions import BoundingBox

# A made-up monitor in the Sunol hills, far from the other tests' sensors
MONITOR = ReferenceReading(
    "LIVE0001", "Live test monitor", 37.6000, -121.9000, datetime(2026, 5, 1, tzinfo=UTC), 8.0
)
SENSOR = Sensor(900101, "Live near", 37.6040, -121.9000, datetime(2026, 5, 1, tzinfo=UTC))
NOW = datetime(2026, 6, 1, 12, 20, tzinfo=UTC)  # runs happen a little after the hour
HOUR = timedelta(hours=1)


def hours(start: datetime, end: datetime) -> list[datetime]:
    return [start + h * HOUR for h in range(int((end - start) / HOUR))]


class FakeAirNow:
    def hourly_pm25(
        self, area: BoundingBox, start: datetime, end: datetime
    ) -> list[ReferenceReading]:
        return [
            ReferenceReading("LIVE0001", "Live test monitor", 37.6, -121.9, t, 8.0)
            for t in hours(start, end + HOUR)
        ]


class FakePurpleAir:
    def __init__(self) -> None:
        self.budget = PointsBudget(5_000)
        self.requests: dict[int, tuple[datetime, datetime]] = {}

    def sensors(self, area: BoundingBox, max_sensors: int = 3000) -> list[Sensor]:
        raise AssertionError("live runs must not search for sensors: it costs points")

    def hourly_readings(
        self, sensor_index: int, start: datetime, end: datetime
    ) -> list[LowcostReading]:
        self.requests[sensor_index] = (start, end)
        self.budget.charge(2 + 4 * len(hours(start, end)))
        return [LowcostReading(sensor_index, t, 6.0, 6.5, 55.0) for t in hours(start, end)]


class FakeOpenMeteo:
    def recent(self, points: Sequence[Point], past_days: int = 1) -> dict[Point, list[WeatherHour]]:
        times = hours(NOW - timedelta(days=5), NOW + timedelta(days=1))
        return {p: [WeatherHour(t, 15.0, 70.0, 10.0, 270.0, 0.0) for t in times] for p in points}


@pytest.fixture(scope="module")
def paired(engine: Engine) -> None:
    """One monitor with one low-cost sensor 450 m away, as the backfill would leave them."""
    with engine.begin() as connection:
        store.upsert_reference_stations(connection, [MONITOR])
        store.upsert_lowcost_sensors(connection, [SENSOR])
        store.refresh_sensor_pairs(connection, 1000.0)


def run(engine: Engine, now: datetime) -> FakePurpleAir:
    purpleair = FakePurpleAir()
    run_live_ingestion(engine, FakeAirNow(), purpleair, FakeOpenMeteo(), now=now)
    return purpleair


def test_new_sensor_starts_with_the_last_three_hours() -> None:
    end = datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert lowcost_window(None, end) == end - 3 * HOUR


def test_each_run_continues_after_the_newest_stored_hour(engine: Engine, paired: None) -> None:
    first = run(engine, NOW)
    second = run(engine, NOW + 3 * HOUR)

    end = datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert first.requests[SENSOR.sensor_index] == (end - 3 * HOUR, end)
    assert second.requests[SENSOR.sensor_index] == (end, end + 3 * HOUR)


def test_catch_up_after_an_outage_is_capped_at_one_day(engine: Engine, paired: None) -> None:
    later = NOW + timedelta(days=3)
    purpleair = run(engine, later)

    end = datetime(2026, 6, 4, 12, tzinfo=UTC)
    assert purpleair.requests[SENSOR.sensor_index] == (end - timedelta(days=1), end)


def test_an_up_to_date_sensor_spends_no_points(engine: Engine, paired: None) -> None:
    later = NOW + timedelta(days=3)
    run(engine, later)

    purpleair = run(engine, later)

    assert SENSOR.sensor_index not in purpleair.requests


def test_runs_are_recorded(engine: Engine, paired: None) -> None:
    run(engine, NOW + timedelta(days=10))

    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM ingestion_runs WHERE task = 'live' ORDER BY id DESC LIMIT 1")
        ).scalar_one()
    assert status == "succeeded"


def test_a_run_is_skipped_while_another_holds_the_lock(engine: Engine, paired: None) -> None:
    with engine.connect() as other_run:
        other_run.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        purpleair = FakePurpleAir()
        report = run_live_ingestion(
            engine, FakeAirNow(), purpleair, FakeOpenMeteo(), now=NOW + timedelta(days=20)
        )
        other_run.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})

    assert report.skipped
    assert purpleair.requests == {}
