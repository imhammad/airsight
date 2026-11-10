from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from airsight.api.deps import get_connection, get_now
from airsight.api.main import create_app
from airsight.api.store import MemoryStore
from airsight.core.tables import corrected_readings
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ml import serving
from airsight.ml.serving import Choice, choose, choose_sources

# Made-up monitors near Eureka, in a month no other test uses. Every monitor reads 10.
NOW = datetime(2026, 6, 15, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
MODEL = "airsight-correction/1"
# Raw 8 is 2 off and corrected 13 is 3 off, for 250 hours: the correction loses here
LOSING = Sensor(960001, "Losing", 40.8030, -124.1500, NOW)
# Raw 14 is 4 off and corrected 10.5 is 0.5 off: the correction wins
WINNING = Sensor(960002, "Winning", 40.7030, -124.1500, NOW)
# Loses like LOSING, but over only 100 hours: too little evidence to switch
THIN = Sensor(960003, "Thin", 40.6030, -124.1500, NOW)
VALUES = {LOSING: (8.0, 13.0, 250), WINNING: (14.0, 10.5, 250), THIN: (8.0, 13.0, 100)}


@pytest.fixture(scope="module")
def ids(engine: Engine) -> Iterator[dict[int, int]]:
    monitors = [
        ReferenceReading(station, name, latitude, -124.1500, NOW - h * HOUR, 10.0)
        for station, name, latitude in [
            ("SRV00001", "Losing monitor", 40.8000),
            ("SRV00002", "Winning monitor", 40.7000),
            ("SRV00003", "Thin monitor", 40.6000),
        ]
        for h in range(1, 251)
    ]
    with engine.begin() as connection:
        stations = store.upsert_reference_stations(connection, monitors)
        store.upsert_reference_readings(connection, monitors, stations)
        ids = store.upsert_lowcost_sensors(connection, list(VALUES))
        store.refresh_sensor_pairs(connection, max_distance_m=1000)
        for sensor, (raw, corrected, hours) in VALUES.items():
            times = [NOW - h * HOUR for h in range(1, hours + 1)]
            store.upsert_lowcost_readings(
                connection,
                [LowcostReading(sensor.sensor_index, t, raw, raw, 50.0) for t in times],
                ids,
            )
            connection.execute(
                corrected_readings.insert(),
                [
                    {
                        "sensor_id": ids[sensor.sensor_index],
                        "time": t,
                        "pm25": corrected,
                        "model_version": MODEL,
                    }
                    for t in times
                ],
            )
    yield ids

    sensor_ids = list(ids.values())
    station_ids = list(stations.values())
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM serving_sources"))  # derived, rebuilt by every run
        for table in ("corrected_readings", "lowcost_readings"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE sensor_id = ANY(:ids)"), {"ids": sensor_ids}
            )
        connection.execute(
            text("DELETE FROM sensor_pairs WHERE lowcost_sensor_id = ANY(:ids)"),
            {"ids": sensor_ids},
        )
        connection.execute(
            text("DELETE FROM reference_readings WHERE sensor_id = ANY(:ids)"), {"ids": station_ids}
        )
        connection.execute(
            text("DELETE FROM sensors WHERE id = ANY(:ids)"), {"ids": sensor_ids + station_ids}
        )


def ours(choices: list[Choice], ids: dict[int, int]) -> dict[str, Choice]:
    names = {ids[sensor.sensor_index]: sensor.name for sensor in VALUES}
    return {names[c.sensor_id]: c for c in choices if c.sensor_id in names}


@pytest.mark.parametrize(
    ("hours", "corrected_mae", "raw_mae", "source"),
    [
        (200, 3.0, 2.0, "raw"),  # enough hours, and the correction is worse
        (199, 3.0, 2.0, "corrected"),  # not enough hours yet
        (500, 2.0, 3.0, "corrected"),  # the correction is better
        (500, 2.0, 2.0, "corrected"),  # a tie keeps the correction
        (0, None, None, "corrected"),  # nothing scored
    ],
)
def test_raw_needs_enough_evidence_that_the_correction_is_worse(
    hours: int, corrected_mae: float | None, raw_mae: float | None, source: str
) -> None:
    assert choose(hours, corrected_mae, raw_mae) == source


def test_each_sensor_follows_its_monitor_score(engine: Engine, ids: dict[int, int]) -> None:
    choices = ours(choose_sources(engine, MODEL, NOW), ids)

    assert {name: c.source for name, c in choices.items()} == {
        "Losing": "raw",
        "Winning": "corrected",
        "Thin": "corrected",
    }
    assert choices["Losing"].hours == 250
    assert choices["Losing"].corrected_mae == pytest.approx(3.0)
    assert choices["Losing"].raw_mae == pytest.approx(2.0)
    assert choices["Thin"].hours == 100


def test_only_the_last_14_days_count(engine: Engine, ids: dict[int, int]) -> None:
    # Ten days later, only 4 days of LOSING's 250 hours are still in the window
    choices = ours(choose_sources(engine, MODEL, NOW + timedelta(days=10)), ids)

    assert choices["Losing"].source == "corrected"
    assert choices["Losing"].hours == 14 * 24 - 10 * 24


def test_a_new_champion_starts_on_corrected(engine: Engine, ids: dict[int, int]) -> None:
    choose_sources(engine, MODEL, NOW)

    # Its own corrections haven't been scored yet, so the old model's record doesn't count
    choices = ours(choose_sources(engine, "airsight-correction/2", NOW), ids)

    assert {c.source for c in choices.values()} == {"corrected"}
    assert {c.hours for c in choices.values()} == {0}


def test_choices_are_stored(engine: Engine, ids: dict[int, int]) -> None:
    choose_sources(engine, MODEL, NOW)

    with engine.connect() as connection:
        stored: dict[int, str] = dict(
            connection.execute(
                text("SELECT sensor_id, source FROM serving_sources WHERE sensor_id = ANY(:ids)"),
                {"ids": list(ids.values())},
            ).all()
        )

    assert sorted(stored.values()) == ["corrected", "corrected", "raw"]


def test_choosing_is_logged(
    engine: Engine, ids: dict[int, int], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger=serving.__name__)

    choose_sources(engine, MODEL, NOW)

    assert "monitors showing raw" in caplog.text


@pytest.fixture
def client(engine: Engine, ids: dict[int, int]) -> TestClient:
    choose_sources(engine, MODEL, NOW)

    def test_connection() -> Iterator[Connection]:
        with engine.connect() as connection:
            yield connection

    app = create_app(store=MemoryStore(), rate_limit_per_minute=0)
    app.dependency_overrides[get_connection] = test_connection
    app.dependency_overrides[get_now] = lambda: NOW
    return TestClient(app)


def test_a_raw_sensor_shows_its_own_reading(client: TestClient) -> None:
    reading = client.get("/v1/sensors/pa-960001").json()["latest_reading"]

    assert reading["source"] == "raw"
    assert reading["pm25"] == 8.0
    assert reading["aqi_category"] == "good"  # the category of what's shown, not of 13.0
    assert reading["pm25_corrected"] == 13.0  # still there, for anyone who wants it


def test_a_corrected_sensor_shows_the_correction(client: TestClient) -> None:
    reading = client.get("/v1/sensors/pa-960002").json()["latest_reading"]

    assert reading["source"] == "corrected"
    assert reading["pm25"] == 10.5
    assert reading["aqi_category"] == "moderate"


def test_every_endpoint_shows_the_same_choice(client: TestClient) -> None:
    latest = client.get("/v1/readings/latest").json()["data"]
    losing = next(s for s in latest if s["id"] == "pa-960001")
    nearest = client.get("/v1/readings/nearest", params={"lat": 40.8030, "lon": -124.1500}).json()
    start = (NOW - 3 * HOUR).isoformat()
    history = client.get(
        "/v1/sensors/pa-960001/history", params={"start": start, "end": NOW.isoformat()}
    )

    assert losing["latest_reading"]["source"] == "raw"
    assert nearest["data"][0]["reading"]["source"] == "raw"
    assert [r["source"] for r in history.json()["data"]] == ["raw", "raw", "raw"]
