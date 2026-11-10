from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from airsight.api import deps
from airsight.api.deps import get_champion, get_connection, get_now
from airsight.api.main import create_app
from airsight.api.schemas import ModelInfo
from airsight.api.store import MemoryStore
from airsight.core.config import get_settings
from airsight.core.tables import corrected_readings
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ml.registry import CHAMPION, MODEL_NAME

# Made-up monitors near Oroville, in a month no other test uses
NOW = datetime(2026, 4, 15, 12, tzinfo=UTC)
TRAINED_BEFORE = NOW - timedelta(days=3)
HOUR = timedelta(hours=1)
NORTH_MONITOR = (39.6000, -121.5500)
SOUTH_MONITOR = (39.5000, -121.5500)
SOUTH_1 = Sensor(950101, "South 1", 39.5030, -121.5500, NOW)
SOUTH_2 = Sensor(950102, "South 2", 39.5000, -121.5540, NOW)
NORTH_1 = Sensor(950103, "North 1", 39.6030, -121.5500, NOW)
CHAMPION_INFO = ModelInfo(
    name=MODEL_NAME,
    version=3,
    model_version=f"{MODEL_NAME}/3",
    dataset="abc123",
    trained_before=TRAINED_BEFORE,
    promoted_at=TRAINED_BEFORE,
    final_test=None,
    model_card="https://example.com/card",
)


@pytest.fixture
def local_mlflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """An empty MLflow registry in tmp_path, used by both the test and the API."""
    monkeypatch.chdir(tmp_path)  # MLflow writes model files to ./mlruns
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    get_settings.cache_clear()
    mlflow.set_tracking_uri(uri)
    yield
    get_settings.cache_clear()


def promote_fake_champion() -> str:
    """Register a tiny model the way ml/registry.promote does, with final-test metrics."""
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"raw": rng.uniform(0, 50, 200)})
    booster = lgb.train({"verbose": -1}, lgb.Dataset(frame, label=frame["raw"]), 5)
    with mlflow.start_run() as run:
        mlflow.log_metrics(
            {
                "final.lightgbm.headline_mae": 2.5012,
                "final.raw.headline_mae": 2.8749,
                "final.epa.headline_mae": 3.4201,
                "final.lightgbm.all.hours": 3021.0,
            }
        )
        logged = mlflow.lightgbm.log_model(booster, name="model")
    version = mlflow.register_model(logged.model_uri, MODEL_NAME)
    client = mlflow.MlflowClient()
    client.set_model_version_tag(MODEL_NAME, version.version, "dataset", "f5a557c189d5")
    client.set_model_version_tag(
        MODEL_NAME, version.version, "trained_before", "2026-10-23T00:00:00+00:00"
    )
    client.set_registered_model_alias(MODEL_NAME, CHAMPION, version.version)
    return str(run.info.run_id)


def test_model_describes_the_champion(local_mlflow: None) -> None:
    promote_fake_champion()

    body = (
        TestClient(create_app(store=MemoryStore(), rate_limit_per_minute=0)).get("/v1/model").json()
    )

    assert {k: v for k, v in body.items() if k != "promoted_at"} == {
        "name": "airsight-correction",
        "version": 1,
        "model_version": "airsight-correction/1",
        "dataset": "f5a557c189d5",
        "trained_before": "2026-10-23T00:00:00Z",
        "final_test": {
            "headline_mae": 2.5,
            "raw_headline_mae": 2.87,
            "epa_headline_mae": 3.42,
            "hours": 3021,
        },
        "model_card": "https://github.com/imhammad/airsight/blob/main/docs/model-cards/"
        "airsight-correction-v1.md",
    }
    assert body["promoted_at"].endswith("Z")


def test_model_is_503_before_any_promotion(local_mlflow: None) -> None:
    response = TestClient(create_app(store=MemoryStore(), rate_limit_per_minute=0)).get("/v1/model")

    assert response.status_code == 503


@pytest.fixture(scope="module")
def accuracy_client(engine: Engine) -> Iterator[TestClient]:
    """Official monitors read 10. Every hour before TRAINED_BEFORE is wildly wrong on purpose."""
    hours = [NOW - h * HOUR for h in range(1, 97)]  # the last 4 days
    corrected = {SOUTH_1: 11.0, SOUTH_2: 9.0, NORTH_1: 13.0}
    with engine.begin() as connection:
        monitors = [
            ReferenceReading(station, name, *location, t, 10.0)
            for station, name, location in [
                ("ACC00001", "South monitor", SOUTH_MONITOR),
                ("ACC00002", "North monitor", NORTH_MONITOR),
            ]
            for t in hours
        ]
        stations = store.upsert_reference_stations(connection, monitors)
        store.upsert_reference_readings(connection, monitors, stations)
        ids = store.upsert_lowcost_sensors(connection, list(corrected))
        store.refresh_sensor_pairs(connection, max_distance_m=1000)
        readings = [
            LowcostReading(s.sensor_index, t, 14.0, 14.0, 50.0) for s in corrected for t in hours
        ]
        store.upsert_lowcost_readings(connection, readings, ids)
        rows = [
            {
                "sensor_id": ids[sensor.sensor_index],
                "time": t,
                "pm25": value if t >= TRAINED_BEFORE else 110.0,
                "model_version": CHAMPION_INFO.model_version,
            }
            for sensor, value in corrected.items()
            for t in hours
        ]
        connection.execute(corrected_readings.insert(), rows)

    def test_connection() -> Iterator[Connection]:
        with engine.connect() as connection:
            yield connection

    app = create_app(store=MemoryStore(), rate_limit_per_minute=0)
    app.dependency_overrides[get_connection] = test_connection
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_champion] = lambda: CHAMPION_INFO
    yield TestClient(app)

    sensor_ids = list(ids.values())
    station_ids = list(stations.values())
    with engine.begin() as connection:
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


def test_accuracy_counts_only_hours_the_model_never_trained_on(
    accuracy_client: TestClient,
) -> None:
    body = accuracy_client.get("/v1/accuracy", params={"days": 7}).json()

    assert body["start"] == "2026-04-12T12:00:00Z"  # trained_before, not 7 days ago
    assert body["end"] == "2026-04-15T12:00:00Z"
    assert body["hours"] == 3 * 72
    assert body["stations"] == [
        {
            "station": "North monitor",
            "sensors": 1,
            "hours": 72,
            "mae": {"corrected": 3.0, "raw": 4.0, "epa": 1.22},
            "bias": 3.0,
            "source": "corrected",
        },
        {
            "station": "South monitor",
            "sensors": 2,
            "hours": 144,
            "mae": {"corrected": 1.0, "raw": 4.0, "epa": 1.22},
            "bias": 0.0,
            "source": "corrected",
        },
    ]
    # The headline is the mean of the station MAEs, so South's two sensors don't count double
    assert body["headline_mae"] == {"corrected": 2.0, "raw": 4.0, "epa": 1.22}


def test_accuracy_window_follows_days(accuracy_client: TestClient) -> None:
    body = accuracy_client.get("/v1/accuracy", params={"days": 1}).json()

    assert body["start"] == "2026-04-14T12:00:00Z"
    assert body["hours"] == 3 * 24


def test_accuracy_ignores_other_model_versions(accuracy_client: TestClient) -> None:
    app = accuracy_client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_champion] = lambda: CHAMPION_INFO.model_copy(
        update={"model_version": f"{MODEL_NAME}/4"}
    )
    try:
        body = accuracy_client.get("/v1/accuracy").json()
    finally:
        app.dependency_overrides[get_champion] = lambda: CHAMPION_INFO

    assert body["hours"] == 0
    assert body["headline_mae"] == {"corrected": None, "raw": None, "epa": None}


@pytest.mark.parametrize("days", [0, 31])
def test_accuracy_rejects_bad_days(accuracy_client: TestClient, days: int) -> None:
    assert accuracy_client.get("/v1/accuracy", params={"days": days}).status_code == 422


def test_accuracy_is_503_before_any_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "load_champion_info", lambda: None)

    assert (
        TestClient(create_app(store=MemoryStore(), rate_limit_per_minute=0))
        .get("/v1/accuracy")
        .status_code
        == 503
    )


def test_accuracy_says_which_stations_show_raw(accuracy_client: TestClient, engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO serving_sources
                    (sensor_id, station_id, source, hours, model_version, decided_at)
                SELECT p.lowcost_sensor_id, p.reference_sensor_id, 'raw', 72, :model, :now
                FROM sensor_pairs p JOIN sensors m ON m.id = p.reference_sensor_id
                WHERE m.name = 'North monitor'
            """),
            {"model": CHAMPION_INFO.model_version, "now": NOW},
        )
    try:
        body = accuracy_client.get("/v1/accuracy", params={"days": 2}).json()
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM serving_sources"))

    assert {s["station"]: s["source"] for s in body["stations"]} == {
        "North monitor": "raw",
        "South monitor": "corrected",
    }
