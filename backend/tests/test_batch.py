from datetime import UTC, datetime, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from celery.schedules import crontab
from sqlalchemy import Engine, select

from airsight.core.tables import corrected_readings, sensor_health
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.open_meteo import WeatherHour
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ingestion.regions import weather_cell
from airsight.ml import batch
from airsight.ml.features import FEATURE_COLUMNS, INPUT_COLUMNS
from airsight.ml.predict import correct
from airsight.worker import tasks
from airsight.worker.celery_app import app

# A made-up monitor near Pinnacles, in a month no other test uses
MONITOR = (36.5000, -121.2000)
START = datetime(2025, 11, 1, tzinfo=UTC)
END = START + timedelta(hours=24)
HOUR = timedelta(hours=1)
CLEAN = Sensor(900401, "Clean", 36.5030, -121.2000, START)
EXCLUDED = Sensor(900402, "Excluded", 36.5000, -121.2040, START)
# Reports no humidity, like Curtis St and GWR Shields Reid (#100), two days after the others
NO_HUMIDITY = Sensor(900403, "No humidity", 36.4970, -121.2000, START)
LATER = START + timedelta(days=2)


@pytest.fixture(scope="module")
def booster() -> lgb.Booster:
    """A small model that learned 'official = 60% of raw'."""
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({column: rng.uniform(0, 50, 2000) for column in FEATURE_COLUMNS})
    data = lgb.Dataset(frame, label=0.6 * frame["raw"])
    return lgb.train({"objective": "l1", "verbose": -1, "seed": 1}, data, num_boost_round=50)


@pytest.fixture(scope="module")
def v1_booster() -> lgb.Booster:
    """A model trained with v1's features, which include the sensor's own humidity."""
    columns = [*FEATURE_COLUMNS[:2], "sensor_humidity", *FEATURE_COLUMNS[2:]]
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({column: rng.uniform(0, 50, 2000) for column in columns})
    data = lgb.Dataset(frame, label=0.6 * frame["raw"])
    return lgb.train({"objective": "l1", "verbose": -1, "seed": 1}, data, num_boost_round=50)


@pytest.fixture(scope="module")
def no_humidity(engine: Engine) -> int:
    """Six clean hours, with weather, from a sensor that reports no humidity."""
    hours = [LATER + h * HOUR for h in range(6)]
    weather = [WeatherHour(t, 12.0, 75.0, 4.0, 300.0, 0.0) for t in hours]
    with engine.begin() as connection:
        ids = store.upsert_lowcost_sensors(connection, [NO_HUMIDITY])
        cell = weather_cell(NO_HUMIDITY.latitude, NO_HUMIDITY.longitude)
        store.upsert_weather(connection, cell, weather)
        readings = [LowcostReading(NO_HUMIDITY.sensor_index, t, 10.0, 11.0, None) for t in hours]
        store.upsert_lowcost_readings(connection, readings, ids)
    return ids[NO_HUMIDITY.sensor_index]


@pytest.fixture(scope="module")
def one_day(engine: Engine) -> dict[int, int]:
    """A clean sensor and an excluded one, 24 hours each, with weather. Hour 5 is flagged."""
    hours = [START + h * HOUR for h in range(24)]
    reference = [ReferenceReading("BATCH001", "Batch monitor", *MONITOR, t, 7.0) for t in hours]
    weather = [WeatherHour(t, 12.0, 75.0, 4.0, 300.0, 0.0) for t in hours]
    with engine.begin() as connection:
        station_ids = store.upsert_reference_stations(connection, reference)
        store.upsert_reference_readings(connection, reference, station_ids)
        ids = store.upsert_lowcost_sensors(connection, [CLEAN, EXCLUDED])
        store.upsert_weather(connection, weather_cell(CLEAN.latitude, CLEAN.longitude), weather)
        for sensor in (CLEAN, EXCLUDED):
            readings = [
                LowcostReading(
                    sensor.sensor_index, t, *((2.0, 20.0) if h == 5 else (10.0, 11.0)), 60.0
                )
                for h, t in enumerate(hours)
            ]
            store.upsert_lowcost_readings(connection, readings, ids)
        connection.execute(
            sensor_health.insert().values(
                sensor_id=ids[EXCLUDED.sensor_index],
                checked_at=END,
                window_start=START,
                hours=24,
                impossible_share=0.5,
                disagree_share=0.0,
                status="excluded",
                reason="test",
            )
        )
    return ids


def stored(engine: Engine, sensor_id: int) -> pd.DataFrame:
    query = select(corrected_readings).where(corrected_readings.c.sensor_id == sensor_id)
    with engine.connect() as connection:
        return pd.read_sql(query.order_by(corrected_readings.c.time), connection)


def test_clean_hours_of_healthy_sensors_are_corrected(
    engine: Engine, one_day: dict[int, int], booster: lgb.Booster
) -> None:
    count = batch.correct_window(engine, booster, "airsight-correction/1", START, END)

    clean = stored(engine, one_day[CLEAN.sensor_index])
    assert count == 23  # 24 hours minus the flagged one
    assert len(clean) == 23
    assert START + 5 * HOUR not in set(clean["time"])
    assert set(clean["model_version"]) == {"airsight-correction/1"}
    assert stored(engine, one_day[EXCLUDED.sensor_index]).empty


def test_stored_values_are_the_serving_predictions(
    engine: Engine, one_day: dict[int, int], booster: lgb.Booster
) -> None:
    batch.correct_window(engine, booster, "airsight-correction/1", START, END)
    row = {
        "time": [START],
        "pm25_a": [10.0],
        "pm25_b": [11.0],
        "humidity": [60.0],
        "temperature": [12.0],
        "relative_humidity": [75.0],
        "wind_speed": [4.0],
        "precipitation": [0.0],
    }

    expected = correct(booster, pd.DataFrame(row)[INPUT_COLUMNS]).iloc[0]

    first = stored(engine, one_day[CLEAN.sensor_index]).iloc[0]
    assert first["pm25"] == pytest.approx(expected, rel=1e-6)


def test_sensors_without_humidity_are_corrected(
    engine: Engine, no_humidity: int, booster: lgb.Booster
) -> None:
    count = batch.correct_window(engine, booster, "airsight-correction/2", LATER, LATER + 6 * HOUR)

    assert count == 6
    assert len(stored(engine, no_humidity)) == 6


def test_a_model_that_needs_sensor_humidity_skips_them(
    engine: Engine, no_humidity: int, v1_booster: lgb.Booster
) -> None:
    count = batch.correct_window(
        engine, v1_booster, "airsight-correction/1", LATER, LATER + 6 * HOUR
    )

    assert count == 0


def test_recomputing_replaces_values_and_records_the_new_model(
    engine: Engine, one_day: dict[int, int], booster: lgb.Booster
) -> None:
    batch.correct_window(engine, booster, "airsight-correction/1", START, END)

    batch.correct_window(engine, booster, "airsight-correction/2", START, END)

    clean = stored(engine, one_day[CLEAN.sensor_index])
    assert len(clean) == 23
    assert set(clean["model_version"]) == {"airsight-correction/2"}


def test_worker_job_uses_the_champion(
    engine: Engine, one_day: dict[int, int], booster: lgb.Booster, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "load_champion_version", lambda: (booster, "airsight-correction/7"))

    count = batch.correct_recent(engine, now=END)

    assert count == 23
    assert set(stored(engine, one_day[CLEAN.sensor_index])["model_version"]) == {
        "airsight-correction/7"
    }


def test_corrections_run_after_each_live_ingestion() -> None:
    entry = app.conf.beat_schedule["correct-readings"]

    assert entry["task"] == "airsight.correct_readings"
    assert entry["schedule"] == crontab(minute="30", hour="0,3,6,9,12,15,18,21")
    assert tasks.correct_readings.name == "airsight.correct_readings"
