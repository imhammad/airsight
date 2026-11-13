from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from airsight.api.deps import get_connection, get_now
from airsight.api.main import create_app
from airsight.api.store import MemoryStore
from airsight.core.tables import forecasts
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.purpleair import Sensor

# Made-up monitors near Crescent City, in a month no other test uses
NOW = datetime(2026, 5, 20, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
ISSUED = NOW - 24 * HOUR  # horizons 1 to 23 land before NOW; 24 lands on NOW, outside the window
JUMP_MONITOR = (41.7500, -124.2000)  # reads 10 until the issue hour, then 14
STEADY_MONITOR = (41.8500, -124.2000)  # reads 20 throughout
JUMP = Sensor(980001, "Jump", 41.7530, -124.2000, NOW)
STEADY = Sensor(980002, "Steady", 41.8530, -124.2000, NOW)
MODEL = "airsight-forecast/1"


def jump_forecast(horizon: int) -> tuple[float, float, float]:
    """Off by 1 every hour; the range holds 14 only for the first 6 hours."""
    return (12.0, 13.0, 15.0) if horizon <= 6 else (14.5, 15.0, 16.0)


def rows(
    sensor_id: int, issued: datetime, model: str, ranges: dict[int, tuple[float, float, float]]
) -> list[dict[str, object]]:
    return [
        {
            "sensor_id": sensor_id,
            "issue_time": issued,
            "horizon": horizon,
            "target_time": issued + horizon * HOUR,
            "p10": p10,
            "p50": p50,
            "p90": p90,
            "outside_experience": False,
            "model_version": model,
        }
        for horizon, (p10, p50, p90) in ranges.items()
    ]


@pytest.fixture(scope="module")
def client(engine: Engine) -> Iterator[TestClient]:
    hours = [NOW - h * HOUR for h in range(0, 4 * 24)]
    with engine.begin() as connection:
        monitors = [
            ReferenceReading(
                "FACC0001", "Jump monitor", *JUMP_MONITOR, t, 14.0 if t > ISSUED else 10.0
            )
            for t in hours
        ] + [
            ReferenceReading("FACC0002", "Steady monitor", *STEADY_MONITOR, t, 20.0) for t in hours
        ]
        stations = store.upsert_reference_stations(connection, monitors)
        store.upsert_reference_readings(connection, monitors, stations)
        ids = store.upsert_lowcost_sensors(connection, [JUMP, STEADY])
        store.refresh_sensor_pairs(connection, max_distance_m=1000)
        jump, steady = ids[JUMP.sensor_index], ids[STEADY.sensor_index]
        connection.execute(
            forecasts.insert(),
            rows(jump, ISSUED, MODEL, {h: jump_forecast(h) for h in range(1, 25)})
            + rows(steady, ISSUED, MODEL, {h: (18.0, 20.0, 22.0) for h in range(1, 25)})
            # An older model's issue, wildly wrong: only the newest model is scored
            + rows(
                jump,
                ISSUED - 3 * HOUR,
                "airsight-forecast/0",
                {h: (80, 90, 99) for h in range(1, 25)},
            ),
        )

    def test_connection() -> Iterator[Connection]:
        with engine.connect() as connection:
            yield connection

    app = create_app(store=MemoryStore(), rate_limit_per_minute=0)
    app.dependency_overrides[get_connection] = test_connection
    app.dependency_overrides[get_now] = lambda: NOW + 20 * timedelta(minutes=1)
    yield TestClient(app)

    sensor_ids = list(ids.values())
    station_ids = list(stations.values())
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM forecasts WHERE sensor_id = ANY(:ids)"), {"ids": sensor_ids}
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


def test_each_station_is_scored_against_both_baselines_on_the_same_hours(
    client: TestClient,
) -> None:
    body = client.get("/v1/accuracy/forecast", params={"days": 7}).json()

    assert body["model_version"] == MODEL
    assert body["start"] == "2026-05-13T12:00:00Z"
    assert body["end"] == "2026-05-20T12:00:00Z"
    assert body["hours"] == 2 * 23
    assert body["stations"] == [
        {
            "station": "Jump monitor",
            "sensors": 1,
            "hours": 23,
            "mae": {"forecast": 1.0, "persistence": 4.0, "same_hour_yesterday": 4.0},
            "coverage": 0.26,  # 6 of 23 hours
        },
        {
            "station": "Steady monitor",
            "sensors": 1,
            "hours": 23,
            "mae": {"forecast": 0.0, "persistence": 0.0, "same_hour_yesterday": 0.0},
            "coverage": 1.0,
        },
    ]
    assert body["headline_mae"] == {"forecast": 0.5, "persistence": 2.0, "same_hour_yesterday": 2.0}
    assert body["coverage"] == 0.63


def test_scores_by_hours_ahead_average_the_stations(client: TestClient) -> None:
    groups = client.get("/v1/accuracy/forecast").json()["by_horizon"]

    assert [(g["hours_ahead"], g["hours"], g["coverage"]) for g in groups] == [
        ("1-6", 12, 1.0),
        ("7-12", 12, 0.5),
        ("13-24", 22, 0.5),
    ]
    assert groups[0]["mae"] == {"forecast": 0.5, "persistence": 2.0, "same_hour_yesterday": 2.0}


def test_nothing_to_score_yet(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_now] = lambda: NOW - timedelta(days=10)
    try:
        # days=6, a request no other test makes, so the answer can't come from the cache
        body = client.get("/v1/accuracy/forecast", params={"days": 6}).json()
    finally:
        app.dependency_overrides[get_now] = lambda: NOW + 20 * timedelta(minutes=1)

    assert body["model_version"] is None
    assert body["hours"] == 0
    assert body["coverage"] is None
    assert body["stations"] == []
    assert [g["hours"] for g in body["by_horizon"]] == [0, 0, 0]


@pytest.mark.parametrize("days", [0, 31])
def test_rejects_bad_days(client: TestClient, days: int) -> None:
    assert client.get("/v1/accuracy/forecast", params={"days": days}).status_code == 422
