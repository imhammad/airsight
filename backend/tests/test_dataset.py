from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.open_meteo import WeatherHour
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ingestion.regions import weather_cell
from airsight.ml.dataset import build_dataset, content_hash, load_pairs
from airsight.ml.features import FEATURE_COLUMNS, add_features

# A made-up monitor near Gilroy, in a month no other test uses
MONITOR = (37.0000, -121.5700)
START = datetime(2025, 10, 1, tzinfo=UTC)
END = START + timedelta(days=2)
HOUR = timedelta(hours=1)
CLEAN = Sensor(900301, "Clean", 37.0030, -121.5700, START)
BROKEN = Sensor(900302, "Broken", 37.0000, -121.5740, START)


def lowcost_value(sensor: Sensor, hour: int) -> tuple[float, float]:
    if sensor is BROKEN and hour % 4 == 0:  # 25% impossible hours: excluded
        return 5000.0, 0.0
    if hour % 24 == 7:  # channels disagree: these hours get a flag
        return 2.0, 20.0
    return 10.0, 10.4


@pytest.fixture(scope="module")
def two_days(engine: Engine) -> None:
    """One monitor with a clean and a broken sensor nearby, plus weather, for two days."""
    hours = [START + h * HOUR for h in range(48)]
    reference = [ReferenceReading("DATA0001", "Dataset monitor", *MONITOR, t, 7.0) for t in hours]
    weather = [WeatherHour(t, 15.0, 70.0, 5.0, 270.0, 0.0) for t in hours]
    with engine.begin() as connection:
        station_ids = store.upsert_reference_stations(connection, reference)
        store.upsert_reference_readings(connection, reference, station_ids)
        ids = store.upsert_lowcost_sensors(connection, [CLEAN, BROKEN])
        store.refresh_sensor_pairs(connection, 1000.0)
        store.upsert_weather(connection, weather_cell(CLEAN.latitude, CLEAN.longitude), weather)
        for sensor in (CLEAN, BROKEN):
            readings = [
                LowcostReading(sensor.sensor_index, t, *lowcost_value(sensor, h), 50.0)
                for h, t in enumerate(hours)
            ]
            store.upsert_lowcost_readings(connection, readings, ids)


def test_pairs_keep_clean_hours_of_healthy_sensors(engine: Engine, two_days: None) -> None:
    frame, excluded = load_pairs(engine, START, END)

    assert len(excluded) == 1  # the broken sensor
    assert frame["sensor_id"].nunique() == 1
    assert len(frame) == 46  # 48 hours minus the two flagged ones
    assert frame["official"].eq(7.0).all()
    assert frame["raw"].to_list() == pytest.approx([10.2] * 46)
    assert frame["temperature"].eq(15.0).all()
    assert set(FEATURE_COLUMNS) <= set(frame.columns)


def test_local_hour_uses_california_time(engine: Engine, two_days: None) -> None:
    frame, _ = load_pairs(engine, START, END)

    first = frame.sort_values("time").iloc[0]
    assert first["local_hour"] == 17  # 00:00 UTC on 1 Oct is 17:00 the day before in PDT


def test_dataset_files_are_named_by_content(engine: Engine, two_days: None, tmp_path: Path) -> None:
    first = build_dataset(engine, START, END, tmp_path)
    second = build_dataset(engine, START, END, tmp_path)

    assert first.content_hash == second.content_hash
    assert Path(first.path).name == f"pairs-{first.content_hash}.parquet"
    assert Path(first.path).with_suffix(".json").exists()
    assert first.rows == 46
    assert first.final_test_start == (END - timedelta(days=14)).isoformat()
    stored = pd.read_parquet(first.path)
    assert content_hash(stored) == first.content_hash


def test_features_need_every_input_column() -> None:
    with pytest.raises(ValueError, match="pm25_b"):
        add_features(pd.DataFrame({"time": [], "pm25_a": []}))
