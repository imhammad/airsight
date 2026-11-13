from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from airsight.api.deps import get_connection, get_now
from airsight.api.main import create_app
from airsight.api.store import MemoryStore
from airsight.core.tables import forecasts, sensor_health
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.purpleair import Sensor

# Made-up monitor near Ukiah, where no other test puts sensors
NOW = datetime(2026, 3, 1, 12, 30, tzinfo=UTC)
HERE = (39.1500, -123.2000)
FRESH = Sensor(970001, "Fresh", 39.1530, -123.2000, NOW)  # issued 2 hours ago
OLD = Sensor(970002, "Old", 39.1470, -123.2000, NOW)  # issued 9 hours ago
EXCLUDED = Sensor(970003, "Excluded", 39.1500, -123.2040, NOW)  # has a forecast, but excluded
NEW = Sensor(970004, "New", 39.1500, -123.1960, NOW)  # paired, not forecast yet
MODEL = "airsight-forecast/1"


def forecast_rows(sensor_id: int, issue_time: datetime, p50: float) -> list[dict[str, object]]:
    return [
        {
            "sensor_id": sensor_id,
            "issue_time": issue_time,
            "horizon": horizon,
            "target_time": issue_time + timedelta(hours=horizon),
            "p10": p50 - 2.0,
            "p50": p50 + horizon / 100,
            "p90": p50 + 3.0,
            "outside_experience": p50 > 35.4,
            "model_version": MODEL,
        }
        for horizon in range(24, 0, -1)  # stored out of order on purpose
    ]


@pytest.fixture(scope="module")
def client(engine: Engine) -> Iterator[TestClient]:
    with engine.begin() as connection:
        monitor = ReferenceReading("APIF0001", "Ukiah", *HERE, NOW, 5.0)
        station_ids = list(store.upsert_reference_stations(connection, [monitor]).values())
        ids = store.upsert_lowcost_sensors(connection, [FRESH, OLD, EXCLUDED, NEW])
        store.refresh_sensor_pairs(connection, max_distance_m=1000)
        fresh, old, excluded = (ids[s.sensor_index] for s in (FRESH, OLD, EXCLUDED))
        issued = NOW.replace(minute=0) - timedelta(hours=2)
        connection.execute(
            forecasts.insert(),
            forecast_rows(fresh, issued - timedelta(hours=3), 20.0)  # older issue
            + forecast_rows(fresh, issued, 8.04)
            + forecast_rows(fresh, NOW + timedelta(hours=1), 50.0)  # issued after now
            + forecast_rows(old, NOW.replace(minute=0) - timedelta(hours=9), 40.0)
            + forecast_rows(excluded, issued, 8.0),
        )
        connection.execute(
            sensor_health.insert().values(
                sensor_id=excluded,
                checked_at=NOW,
                window_start=NOW - timedelta(days=7),
                hours=168,
                impossible_share=0.4,
                disagree_share=0.0,
                status="excluded",
                reason="test",
            )
        )

    def test_connection() -> Iterator[Connection]:
        with engine.connect() as connection:
            yield connection

    app = create_app(store=MemoryStore(), rate_limit_per_minute=0)
    app.dependency_overrides[get_connection] = test_connection
    app.dependency_overrides[get_now] = lambda: NOW
    yield TestClient(app)

    # Other tests pair every sensor near a monitor, so these must not outlive this module
    sensor_ids = list(ids.values())
    with engine.begin() as connection:
        for table in ("forecasts", "sensor_health"):
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


def test_forecast_is_the_newest_issue_with_24_hours_soonest_first(client: TestClient) -> None:
    response = client.get("/v1/sensors/pa-970001/forecast")

    assert response.status_code == 200
    body = response.json()
    assert body["sensor_id"] == "pa-970001"
    assert body["issued_at"] == "2026-03-01T10:00:00Z"
    assert body["model_version"] == MODEL
    assert body["stale"] is False
    hours = body["hours"]
    assert [hour["hours_ahead"] for hour in hours] == list(range(1, 25))
    assert hours[0]["target_time"] == "2026-03-01T11:00:00Z"
    assert hours[-1]["target_time"] == "2026-03-02T10:00:00Z"


def test_forecast_values_are_rounded_and_categorized_by_p50(client: TestClient) -> None:
    first = client.get("/v1/sensors/pa-970001/forecast").json()["hours"][0]

    # stored p50 is 8.05: one decimal, like every other PM2.5 the API reports
    assert first["p50"] == pytest.approx(8.1)
    assert first["p10"] == pytest.approx(6.0)
    assert first["p90"] == pytest.approx(11.0)
    assert first["aqi_category"] == "good"
    assert first["outside_experience"] is False


def test_forecast_issued_more_than_6_hours_ago_is_stale(client: TestClient) -> None:
    body = client.get("/v1/sensors/pa-970002/forecast").json()

    assert body["issued_at"] == "2026-03-01T03:00:00Z"
    assert body["stale"] is True
    assert all(hour["outside_experience"] for hour in body["hours"])
    assert body["hours"][0]["aqi_category"] == "unhealthy_sensitive"


@pytest.mark.parametrize("sensor_id", ["pa-970003", "pa-970004"])
def test_excluded_or_not_yet_forecast_sensor_has_no_forecast(
    client: TestClient, sensor_id: str
) -> None:
    response = client.get(f"/v1/sensors/{sensor_id}/forecast")

    assert response.status_code == 404
    assert response.json()["detail"] == f"No forecast for sensor {sensor_id}"


def test_unknown_sensor_is_not_found(client: TestClient) -> None:
    response = client.get("/v1/sensors/pa-0/forecast")

    assert response.status_code == 404
    assert response.json()["detail"] == "No sensor with id pa-0"
