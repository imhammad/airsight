from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from celery.schedules import crontab
from sqlalchemy import Engine, select, text

from airsight.core.tables import forecasts, sensor_health
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.open_meteo import Point, WeatherHour
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ml import forecast_batch
from airsight.ml.forecast_batch import issue_forecast, latest_issue_time, mark_unseen_air
from airsight.worker import tasks
from airsight.worker.celery_app import app

# A made-up monitor near Hollister, in a month no other test uses
MONITOR = (36.8500, -121.4000)
START = datetime(2025, 3, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
ISSUE = START + 26 * HOUR  # 02:00 UTC on 2 March, on the issue schedule
HEALTHY = Sensor(900601, "Forecast healthy", 36.8530, -121.4000, START)
EXCLUDED = Sensor(900602, "Forecast excluded", 36.8470, -121.4000, START)
# Its last reading, at the issue hour itself, is missing a channel
FLAGGED = Sensor(900603, "Forecast flagged", 36.8500, -121.4040, START)


class FakeWeather:
    """The upcoming forecast: 9 °C everywhere, so a test can tell it from observed weather."""

    def __init__(self) -> None:
        self.asked: list[Point] = []

    def upcoming(self, points: Sequence[Point], days: int = 3) -> dict[Point, list[WeatherHour]]:
        self.asked = list(points)
        hours = [START + h * HOUR for h in range(24 * (days + 2))]
        return {p: [WeatherHour(t, 9.0, 80.0, 3.0, 200.0, 0.0) for t in hours] for p in points}


class FakeModel:
    """p50 is the sensor's raw reading now, with a range of half to one and a half of it."""

    def __init__(self) -> None:
        self.inputs = pd.DataFrame()

    def predict(self, data: pd.DataFrame) -> Any:
        self.inputs = data
        return pd.DataFrame(
            {"p10": 0.5 * data["raw_now"], "p50": data["raw_now"], "p90": 1.5 * data["raw_now"]}
        )


@pytest.fixture(scope="module")
def sensors(engine: Engine) -> dict[int, int]:
    """27 hours up to and including the issue hour, for a monitor and three sensors."""
    hours = [START + h * HOUR for h in range(27)]
    reference = [ReferenceReading("FCST0002", "Hollister", *MONITOR, t, 7.0) for t in hours]
    with engine.begin() as connection:
        station_ids = store.upsert_reference_stations(connection, reference)
        store.upsert_reference_readings(connection, reference, station_ids)
        ids = store.upsert_lowcost_sensors(connection, [HEALTHY, EXCLUDED, FLAGGED])
        store.refresh_sensor_pairs(connection, 1000.0)
        readings = [
            LowcostReading(sensor.sensor_index, t, 10.0, None if last else 10.4, 50.0)
            for sensor in (HEALTHY, EXCLUDED, FLAGGED)
            for t in hours
            for last in [sensor is FLAGGED and t == ISSUE]
        ]
        store.upsert_lowcost_readings(connection, readings, ids)
        connection.execute(
            sensor_health.insert().values(
                sensor_id=ids[EXCLUDED.sensor_index],
                checked_at=ISSUE,
                window_start=START,
                hours=27,
                impossible_share=0.5,
                disagree_share=0.0,
                status="excluded",
                reason="test",
            )
        )
    return ids


def stored(engine: Engine, sensor_id: int) -> pd.DataFrame:
    query = select(forecasts).where(forecasts.c.sensor_id == sensor_id)
    with engine.connect() as connection:
        return pd.read_sql(query.order_by(forecasts.c.issue_time, forecasts.c.horizon), connection)


def test_issue_times_follow_the_training_schedule() -> None:
    assert latest_issue_time(datetime(2026, 11, 13, 3, 45, tzinfo=UTC)) == datetime(
        2026, 11, 13, 2, tzinfo=UTC
    )
    # At 02:30 the 02:00 hour isn't complete yet, so the newest issue is 23:00 the day before
    assert latest_issue_time(datetime(2026, 11, 13, 2, 30, tzinfo=UTC)) == datetime(
        2026, 11, 12, 23, tzinfo=UTC
    )


def test_healthy_sensors_get_24_hours_with_the_upcoming_weather(
    engine: Engine, sensors: dict[int, int]
) -> None:
    model, weather = FakeModel(), FakeWeather()

    count = issue_forecast(engine, model, "airsight-forecast/1", weather, ISSUE)

    healthy = stored(engine, sensors[HEALTHY.sensor_index])
    assert count == 24  # neither the excluded sensor nor the flagged one is forecast
    assert healthy["horizon"].tolist() == list(range(1, 25))
    assert (
        healthy["target_time"]
        == healthy["issue_time"] + pd.to_timedelta(healthy["horizon"], unit="h")
    ).all()
    assert healthy["p50"].tolist() == pytest.approx([10.2] * 24)
    assert set(healthy["model_version"]) == {"airsight-forecast/1"}
    assert not healthy["outside_experience"].any()
    assert not healthy["monitor_offline"].any()
    assert stored(engine, sensors[EXCLUDED.sensor_index]).empty
    assert stored(engine, sensors[FLAGGED.sensor_index]).empty
    assert (model.inputs["temperature"] == 9.0).all()  # the forecast, never observed weather
    assert (model.inputs["official_now"] == 7.0).all()


def test_issuing_again_replaces_the_hours(engine: Engine, sensors: dict[int, int]) -> None:
    issue_forecast(engine, FakeModel(), "airsight-forecast/1", FakeWeather(), ISSUE)
    issue_forecast(engine, FakeModel(), "airsight-forecast/2", FakeWeather(), ISSUE)

    healthy = stored(engine, sensors[HEALTHY.sensor_index])
    assert len(healthy) == 24
    assert set(healthy["model_version"]) == {"airsight-forecast/2"}


def test_a_forecast_without_the_monitor_says_so(engine: Engine, sensors: dict[int, int]) -> None:
    window = {"start": ISSUE - 2 * HOUR, "end": ISSUE}
    station = "SELECT id FROM sensors WHERE source_id = 'FCST0002'"
    with engine.begin() as connection:
        connection.execute(
            text(
                f"DELETE FROM reference_readings WHERE sensor_id = ({station}) "
                "AND time BETWEEN :start AND :end"
            ),
            window,
        )
    try:
        model = FakeModel()
        issue_forecast(engine, model, "airsight-forecast/1", FakeWeather(), ISSUE)
    finally:
        with engine.begin() as connection:  # put the monitor back for the tests after this one
            hours = [ISSUE - 2 * HOUR, ISSUE - HOUR, ISSUE]
            reference = [ReferenceReading("FCST0002", "Hollister", *MONITOR, t, 7.0) for t in hours]
            ids = store.upsert_reference_stations(connection, reference)
            store.upsert_reference_readings(connection, reference, ids)

    healthy = stored(engine, sensors[HEALTHY.sensor_index])
    assert model.inputs["official_now"].isna().all()
    assert healthy["monitor_offline"].all()


def test_unseen_air_is_marked_and_widened() -> None:
    rows = pd.DataFrame({"official_now": [8.0, 50.0, None]})
    predicted = pd.DataFrame(
        {"p10": [5.0, 30.0, 34.0], "p50": [8.0, 40.0, 40.0], "p90": [11.0, 50.0, 46.0]}
    )

    marked = mark_unseen_air(rows, predicted)

    assert marked["outside_experience"].tolist() == [False, True, True]
    assert marked["p10"].tolist() == [5.0, 20.0, 20.0]  # clean air is left alone; the rest
    assert marked["p90"].tolist() == [11.0, 60.0, 60.0]  # go from half to 1.5 times p50


def test_worker_job_uses_the_champion(
    engine: Engine, sensors: dict[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        forecast_batch, "load_champion_version", lambda: (FakeModel(), "airsight-forecast/7")
    )
    monkeypatch.setattr(forecast_batch, "OpenMeteoClient", lambda http: FakeWeather())

    count = forecast_batch.forecast_latest(engine, now=ISSUE + HOUR + 45 * timedelta(minutes=1))

    assert count == 24
    assert set(stored(engine, sensors[HEALTHY.sensor_index])["model_version"]) == {
        "airsight-forecast/7"
    }


def test_forecasts_are_issued_after_each_correction_run() -> None:
    entry = app.conf.beat_schedule["issue-forecast"]

    assert entry["task"] == "airsight.issue_forecast"
    assert entry["schedule"] == crontab(minute="45", hour="0,3,6,9,12,15,18,21")
    assert tasks.issue_forecast.name == "airsight.issue_forecast"
