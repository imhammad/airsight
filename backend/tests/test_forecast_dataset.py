from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine

from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.open_meteo import WeatherHour
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ingestion.regions import weather_cell
from airsight.ml.forecast_dataset import build_forecast_dataset, load_forecast_rows

# A made-up monitor near Monterey, in a month no other test uses
MONITOR = (36.6000, -121.8900)
START = datetime(2025, 2, 1, tzinfo=UTC)
END = START + timedelta(days=3)
HOUR = timedelta(hours=1)
SENSOR = Sensor(900501, "Forecast sensor", 36.6030, -121.8900, START)


@pytest.fixture(scope="module")
def three_days(engine: Engine) -> None:
    """A monitor and a sensor, with observed weather at 15 °C and day-ahead weather at 9 °C."""
    hours = [START + h * HOUR for h in range(72)]
    reference = [ReferenceReading("FCST0001", "Forecast monitor", *MONITOR, t, 7.0) for t in hours]
    cell = weather_cell(SENSOR.latitude, SENSOR.longitude)
    with engine.begin() as connection:
        station_ids = store.upsert_reference_stations(connection, reference)
        store.upsert_reference_readings(connection, reference, station_ids)
        ids = store.upsert_lowcost_sensors(connection, [SENSOR])
        store.refresh_sensor_pairs(connection, 1000.0)
        store.upsert_weather(
            connection, cell, [WeatherHour(t, 15.0, 70.0, 5.0, 270.0, 0.0) for t in hours]
        )
        store.upsert_day_ahead_weather(
            connection, cell, [WeatherHour(t, 9.0, 80.0, 3.0, 200.0, 0.1) for t in hours]
        )
        readings = [LowcostReading(SENSOR.sensor_index, t, 10.0, 10.4, 50.0) for t in hours]
        store.upsert_lowcost_readings(connection, readings, ids)


def test_rows_are_labelled_and_use_day_ahead_weather(engine: Engine, three_days: None) -> None:
    rows, excluded = load_forecast_rows(engine, START, END)

    assert excluded == set()
    assert rows["official"].eq(7.0).all()
    assert rows["raw_now"].tolist() == pytest.approx([10.2] * len(rows))
    assert rows["temperature"].eq(9.0).all()  # the forecast, never the 15 °C that happened
    # 24 issue hours in 3 days, but the last one's targets are all after END: no labels
    assert rows["issue_time"].nunique() == 23
    assert (rows["target_time"] < END).all()


def test_dataset_files_are_named_by_content(
    engine: Engine, three_days: None, tmp_path: Path
) -> None:
    first = build_forecast_dataset(engine, START, END, tmp_path)
    second = build_forecast_dataset(engine, START, END, tmp_path)

    assert first.content_hash == second.content_hash
    assert Path(first.path).name == f"forecast-{first.content_hash}.parquet"
    assert first.sensors == 1
    assert first.final_test_start == (END - timedelta(days=14)).isoformat()
