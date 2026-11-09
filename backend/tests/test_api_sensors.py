from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from airsight.api.aqi import aqi_category
from airsight.api.deps import get_connection, get_now
from airsight.api.main import create_app
from airsight.api.store import MemoryStore
from airsight.core.tables import corrected_readings, sensor_health
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.purpleair import LowcostReading, Sensor

# Made-up monitors near Point Arena, where no other test puts sensors
NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
HERE = (38.9000, -123.7000)
SEEN = NOW - timedelta(days=1)
NEAR = Sensor(950001, "Near", 38.9030, -123.7000, SEEN)  # ~330 m from HERE
FAR = Sensor(950002, "Far", 38.9000, -123.7080, SEEN)  # ~690 m, last reading 8 hours old
EXCLUDED = Sensor(950003, "Excluded", 38.8975, -123.7000, SEEN)  # ~280 m, excluded
NORTH = Sensor(950004, "North", 38.9455, -123.7000, SEEN)  # ~5 km, next to a second monitor
UNPAIRED = Sensor(950005, "Unpaired", 38.9200, -123.7000, SEEN)  # >1 km from any monitor


@pytest.fixture(scope="module")
def client(engine: Engine) -> Iterator[TestClient]:
    with engine.begin() as connection:
        monitors = [
            ReferenceReading("API00001", "Point Arena", *HERE, NOW, 5.0),
            ReferenceReading("API00002", "Point Arena North", 38.9450, -123.7000, NOW, 5.0),
        ]
        station_ids = list(store.upsert_reference_stations(connection, monitors).values())
        ids = store.upsert_lowcost_sensors(connection, [NEAR, FAR, EXCLUDED, NORTH, UNPAIRED])
        store.refresh_sensor_pairs(connection, max_distance_m=1000)
        hours = {
            NEAR: [NOW - timedelta(hours=5), NOW - timedelta(hours=1)],
            FAR: [NOW - timedelta(hours=8)],
            EXCLUDED: [NOW - timedelta(hours=1)],
            NORTH: [NOW - timedelta(hours=1)],
        }
        for sensor, times in hours.items():
            store.upsert_lowcost_readings(
                connection,
                [LowcostReading(sensor.sensor_index, t, 12.0, 13.0, 50.0) for t in times],
                ids,
            )
            connection.execute(
                corrected_readings.insert(),
                [
                    {
                        "sensor_id": ids[sensor.sensor_index],
                        "time": t,
                        "pm25": 7.43 + i,
                        "model_version": "airsight-correction/1",
                    }
                    for i, t in enumerate(times)
                ],
            )
        connection.execute(
            sensor_health.insert().values(
                sensor_id=ids[EXCLUDED.sensor_index],
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
        for table in ("corrected_readings", "lowcost_readings", "sensor_health"):
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


def nearest_ids(client: TestClient, **params: float) -> list[str]:
    response = client.get("/v1/readings/nearest", params={"lat": HERE[0], "lon": HERE[1], **params})
    assert response.status_code == 200
    return [item["sensor"]["id"] for item in response.json()["data"]]


def test_sensor_shows_its_latest_reading_with_provenance(client: TestClient) -> None:
    response = client.get("/v1/sensors/pa-950001")

    assert response.status_code == 200
    assert response.json() == {
        "id": "pa-950001",
        "name": "Near",
        "latitude": pytest.approx(38.9030),
        "longitude": pytest.approx(-123.7000),
        "health": "ok",
        "latest_reading": {
            "pm25_corrected": 8.4,  # the newer of the two hours: 7.43 + 1, one decimal
            "pm25_raw": 12.5,
            "aqi_category": "good",
            "model_version": "airsight-correction/1",
            "observed_at": "2026-03-01T11:00:00Z",
            "stale": False,
        },
    }


def test_old_readings_are_marked_stale(client: TestClient) -> None:
    reading = client.get("/v1/sensors/pa-950002").json()["latest_reading"]

    assert reading["observed_at"] == "2026-03-01T04:00:00Z"
    assert reading["stale"] is True


def test_excluded_sensor_is_listed_without_a_value(client: TestClient) -> None:
    sensor = client.get("/v1/sensors/pa-950003").json()

    assert sensor["health"] == "excluded"
    assert sensor["latest_reading"] is None


@pytest.mark.parametrize("sensor_id", ["pa-999999999", "pa-950005", "xx-950001", "pa-abc", "42"])
def test_unknown_sensor_is_404(client: TestClient, sensor_id: str) -> None:
    assert client.get(f"/v1/sensors/{sensor_id}").status_code == 404


def test_nearest_returns_healthy_sensors_nearest_first(client: TestClient) -> None:
    assert nearest_ids(client, radius_km=2) == ["pa-950001", "pa-950002"]
    assert nearest_ids(client, radius_km=10) == ["pa-950001", "pa-950002", "pa-950004"]
    assert nearest_ids(client, radius_km=10, limit=1) == ["pa-950001"]


def test_nearest_reports_the_distance(client: TestClient) -> None:
    response = client.get("/v1/readings/nearest", params={"lat": HERE[0], "lon": HERE[1]})

    body = response.json()
    assert body["next_cursor"] is None
    assert body["data"][0]["distance_km"] == pytest.approx(0.33, abs=0.01)
    assert body["data"][0]["reading"]["model_version"] == "airsight-correction/1"


@pytest.mark.parametrize(
    "params",
    [
        {"lat": 100, "lon": -123.7},
        {"lat": 38.9, "lon": -200},
        {"lat": 38.9},
        {"lat": 38.9, "lon": -123.7, "radius_km": 0},
        {"lat": 38.9, "lon": -123.7, "radius_km": 51},
        {"lat": 38.9, "lon": -123.7, "limit": 21},
    ],
)
def test_nearest_rejects_bad_input(client: TestClient, params: dict[str, float]) -> None:
    assert client.get("/v1/readings/nearest", params=params).status_code == 422


def test_sensor_pages_cover_every_served_sensor_once(client: TestClient) -> None:
    seen: list[dict[str, object]] = []
    cursor = None
    while True:
        params: dict[str, str | int] = (
            {"limit": 2} if cursor is None else {"limit": 2, "cursor": cursor}
        )
        body = client.get("/v1/sensors", params=params).json()
        assert len(body["data"]) <= 2
        seen.extend(body["data"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    ids = [sensor["id"] for sensor in seen]
    assert len(ids) == len(set(ids))
    assert {"pa-950001", "pa-950002", "pa-950003", "pa-950004"} <= set(ids)
    assert "pa-950005" not in ids  # not near an official monitor, so not served
    assert {"id": "pa-950003", "health": "excluded"}.items() <= next(
        s for s in seen if s["id"] == "pa-950003"
    ).items()


def test_sensor_list_rejects_bad_paging(client: TestClient) -> None:
    assert client.get("/v1/sensors", params={"limit": 201}).status_code == 422
    assert client.get("/v1/sensors", params={"cursor": "not-a-cursor"}).status_code == 400


@pytest.mark.parametrize(
    ("pm25", "category"),
    [
        (0.0, "good"),
        (9.0, "good"),
        (9.04, "good"),  # reported as 9.0
        (9.1, "moderate"),
        (35.4, "moderate"),
        (35.5, "unhealthy_sensitive"),
        (55.5, "unhealthy"),
        (125.5, "very_unhealthy"),
        (225.5, "hazardous"),
    ],
)
def test_aqi_categories_follow_the_2024_breakpoints(pm25: float, category: str) -> None:
    assert aqi_category(pm25) == category


def history(client: TestClient, sensor_id: str, start: str, end: str) -> list[dict[str, object]]:
    response = client.get(f"/v1/sensors/{sensor_id}/history", params={"start": start, "end": end})
    assert response.status_code == 200
    data: list[dict[str, object]] = response.json()["data"]
    return data


def test_history_returns_hourly_readings_oldest_first(client: TestClient) -> None:
    readings = history(client, "pa-950001", "2026-03-01T06:00:00Z", "2026-03-01T12:00:00Z")

    assert [r["observed_at"] for r in readings] == ["2026-03-01T07:00:00Z", "2026-03-01T11:00:00Z"]
    assert [r["pm25_corrected"] for r in readings] == [7.4, 8.4]


def test_history_includes_start_and_excludes_end(client: TestClient) -> None:
    readings = history(client, "pa-950001", "2026-03-01T07:00:00Z", "2026-03-01T11:00:00Z")

    assert [r["observed_at"] for r in readings] == ["2026-03-01T07:00:00Z"]


def test_history_accepts_other_time_zones(client: TestClient) -> None:
    # 23:00 in California on 28 February is 07:00 UTC on 1 March
    readings = history(client, "pa-950001", "2026-02-28T23:00:00-08:00", "2026-03-01T08:00:00Z")

    assert [r["observed_at"] for r in readings] == ["2026-03-01T07:00:00Z"]


def test_history_of_an_excluded_sensor_is_empty(client: TestClient) -> None:
    assert history(client, "pa-950003", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z") == []


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-03-01T06:00:00", "2026-03-01T12:00:00Z"),  # no time zone: rejected, not guessed
        ("2026-03-01T12:00:00Z", "2026-03-01T06:00:00Z"),  # end before start
        ("2026-03-01T12:00:00Z", "2026-03-01T12:00:00Z"),  # empty range
        ("2026-01-01T00:00:00Z", "2026-02-02T00:00:00Z"),  # more than 31 days
        ("yesterday", "2026-03-01T12:00:00Z"),
    ],
)
def test_history_rejects_bad_ranges(client: TestClient, start: str, end: str) -> None:
    response = client.get("/v1/sensors/pa-950001/history", params={"start": start, "end": end})

    assert response.status_code == 422


def test_history_of_an_unknown_sensor_is_404(client: TestClient) -> None:
    response = client.get(
        "/v1/sensors/pa-999999999/history",
        params={"start": "2026-03-01T00:00:00Z", "end": "2026-03-02T00:00:00Z"},
    )

    assert response.status_code == 404
