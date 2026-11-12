from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, select

from airsight.core.tables import day_ahead_weather, weather
from airsight.ingestion import day_ahead, store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.open_meteo import Point, WeatherHour
from airsight.ingestion.regions import weather_cell

# A made-up monitor in a month no other test uses
MONITOR = ReferenceReading(
    "AHEAD001", "Day-ahead monitor", 36.9, -121.6, datetime(2026, 1, 1, tzinfo=UTC), 5.0
)
CELL = weather_cell(MONITOR.latitude, MONITOR.longitude)
NOW = datetime(2026, 12, 20, 6, 40, tzinfo=UTC)
HOUR = timedelta(hours=1)


class FakePreviousRuns:
    """Answers every day asked for with a wind speed of 12, and records the requests."""

    def __init__(self) -> None:
        self.requests: list[tuple[date, date]] = []

    def day_ahead(
        self, points: Sequence[Point], start: date, end: date
    ) -> dict[Point, list[WeatherHour]]:
        self.requests.append((start, end))
        first = datetime(start.year, start.month, start.day, tzinfo=UTC)
        hours = int((end - start).days + 1) * 24
        times = [first + h * HOUR for h in range(hours)]
        return {p: [WeatherHour(t, 8.0, 80.0, 12.0, 300.0, 0.0) for t in times] for p in points}


@pytest.fixture(scope="module")
def monitor(engine: Engine) -> None:
    with engine.begin() as connection:
        store.upsert_reference_stations(connection, [MONITOR])


def day_ahead_rows(engine: Engine) -> list[datetime]:
    query = select(day_ahead_weather.c.time).where(day_ahead_weather.c.cell_id == CELL)
    with engine.connect() as connection:
        return list(connection.execute(query.order_by(day_ahead_weather.c.time)).scalars())


def test_recent_days_are_loaded_up_to_the_last_complete_hour(engine: Engine, monitor: None) -> None:
    source = FakePreviousRuns()

    rows = day_ahead.load(engine, source, NOW, days=3)

    times = day_ahead_rows(engine)
    assert len(times) == 72
    assert rows >= 72  # every cell in use gets them, and other tests add cells too
    assert times[0] == datetime(2026, 12, 17, 6, tzinfo=UTC)
    assert times[-1] == datetime(2026, 12, 20, 5, tzinfo=UTC)  # 06:00 isn't complete yet
    assert source.requests == [(date(2026, 12, 17), date(2026, 12, 20))]


def test_loading_again_keeps_one_row_per_hour(engine: Engine, monitor: None) -> None:
    day_ahead.load(engine, FakePreviousRuns(), NOW, days=3)

    assert len(day_ahead_rows(engine)) == 72


def test_long_ranges_are_asked_for_a_month_at_a_time(engine: Engine, monitor: None) -> None:
    source = FakePreviousRuns()

    day_ahead.load(engine, source, NOW, days=70)

    assert len(source.requests) == 3
    assert source.requests[0][0] == date(2026, 10, 11)
    assert source.requests[-1][1] == date(2026, 12, 20)


def test_forecasts_never_land_in_observed_weather(engine: Engine, monitor: None) -> None:
    day_ahead.load(engine, FakePreviousRuns(), NOW, days=3)

    query = select(weather.c.time).where(weather.c.cell_id == CELL)
    with engine.connect() as connection:
        assert connection.execute(query).first() is None
