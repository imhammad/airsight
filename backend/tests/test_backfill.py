from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.backfill import backfill
from airsight.ingestion.open_meteo import Point, WeatherHour
from airsight.ingestion.purpleair import LowcostReading, PointsBudget, Sensor
from airsight.ingestion.regions import BoundingBox

# A made-up monitor in the hills east of Oakland, away from other tests' sensors
MONITOR = (37.8500, -122.2000)
NEAR = Sensor(900001, "Near", 37.8545, -122.2000, datetime(2026, 1, 1, tzinfo=UTC))  # ~500 m
FAR = Sensor(900002, "Far", 37.8680, -122.2000, datetime(2026, 1, 1, tzinfo=UTC))  # ~2 km
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=2)


def hours(start: datetime, end: datetime) -> list[datetime]:
    count = int((end - start) / timedelta(hours=1))
    return [start + timedelta(hours=h) for h in range(count)]


class FakeAirNow:
    def hourly_pm25(
        self, area: BoundingBox, start: datetime, end: datetime
    ) -> list[ReferenceReading]:
        return [
            ReferenceReading("TEST0001", "Test monitor", *MONITOR, time, 10.0)
            for time in hours(start, end + timedelta(hours=1))
        ]


class FakePurpleAir:
    def __init__(self) -> None:
        self.budget = PointsBudget(1_000)
        self.history_requests: list[int] = []

    def sensors(self, area: BoundingBox, max_sensors: int = 3000) -> list[Sensor]:
        return [NEAR, FAR]

    def hourly_readings(
        self, sensor_index: int, start: datetime, end: datetime
    ) -> list[LowcostReading]:
        self.history_requests.append(sensor_index)
        return [LowcostReading(sensor_index, t, 12.0, 13.0, 60.0) for t in hours(start, end)]


class FakeOpenMeteo:
    def recent(self, points: Sequence[Point], past_days: int = 2) -> dict[Point, list[WeatherHour]]:
        # Includes a future hour, which must not be stored as if it were observed
        times = hours(START, END + timedelta(hours=1))
        return {p: [WeatherHour(t, 15.0, 70.0, 10.0, 270.0, 0.0) for t in times] for p in points}


def count(engine: Engine, sql: str) -> int:
    with engine.connect() as connection:
        value: int = connection.execute(text(sql)).scalar_one()
        return value


def run(engine: Engine) -> FakePurpleAir:
    purpleair = FakePurpleAir()
    backfill(engine, FakeAirNow(), purpleair, FakeOpenMeteo(), START, END)
    return purpleair


def table_counts(engine: Engine) -> tuple[int, ...]:
    return tuple(
        count(engine, f"SELECT count(*) FROM {table}")
        for table in (
            "sensors",
            "reference_readings",
            "lowcost_readings",
            "weather",
            "sensor_pairs",
        )
    )


def test_only_sensors_within_1_km_are_paired_and_downloaded(engine: Engine) -> None:
    purpleair = run(engine)

    assert purpleair.history_requests == [NEAR.sensor_index]
    pairs = count(
        engine,
        "SELECT count(*) FROM sensor_pairs p JOIN sensors s ON s.id = p.lowcost_sensor_id "
        "WHERE s.source_id IN ('900001', '900002')",
    )
    assert pairs == 1


def test_weather_stores_observed_hours_only(engine: Engine) -> None:
    run(engine)

    latest = count(
        engine,
        "SELECT extract(epoch FROM max(time))::bigint FROM weather WHERE cell_id = '37.9,-122.2'",
    )
    assert latest < END.timestamp()


def test_running_twice_gives_the_same_row_counts(engine: Engine) -> None:
    run(engine)
    first = table_counts(engine)

    run(engine)

    assert table_counts(engine) == first


class RecordingPurpleAir(FakePurpleAir):
    def __init__(self) -> None:
        super().__init__()
        self.windows: dict[int, tuple[datetime, datetime]] = {}

    def hourly_readings(
        self, sensor_index: int, start: datetime, end: datetime
    ) -> list[LowcostReading]:
        self.windows[sensor_index] = (start, end)
        return super().hourly_readings(sensor_index, start, end)


def test_a_longer_backfill_only_downloads_the_older_missing_hours(engine: Engine) -> None:
    run(engine)
    purpleair = RecordingPurpleAir()
    earlier = START - timedelta(days=2)

    backfill(engine, FakeAirNow(), purpleair, FakeOpenMeteo(), earlier, END)

    assert purpleair.windows[NEAR.sensor_index] == (earlier, START)


def test_a_rerun_skips_sensors_that_are_already_loaded(engine: Engine) -> None:
    run(engine)
    purpleair = RecordingPurpleAir()

    backfill(engine, FakeAirNow(), purpleair, FakeOpenMeteo(), START, END)

    assert NEAR.sensor_index not in purpleair.windows
