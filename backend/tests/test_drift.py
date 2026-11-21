from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from celery.schedules import crontab
from sqlalchemy import Engine, select

from airsight.core.tables import input_drift
from airsight.ingestion import store
from airsight.ingestion.open_meteo import WeatherHour
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ingestion.regions import weather_cell
from airsight.observability import drift
from airsight.worker import tasks
from airsight.worker.celery_app import app

# A made-up sensor in the Mojave, in a month no other test uses
START = datetime(2024, 2, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
SENSOR = Sensor(900501, "Drift test", 35.0100, -116.0100, START)
TRAINING_END = START + timedelta(days=10)
NOW = START + timedelta(days=28)


def test_identical_inputs_score_zero() -> None:
    values = pd.Series(np.random.default_rng(0).normal(10, 2, 1000))

    assert drift.drift_score(values, values) == 0.0


def test_the_score_is_the_shift_in_standard_deviations() -> None:
    reference = pd.Series(np.random.default_rng(0).normal(10, 2, 5000))

    # Every value 2 µg/m³ higher is one standard deviation of the reference
    assert drift.drift_score(reference, reference + 2) == pytest.approx(1.0, rel=0.02)


def test_an_input_that_never_varied_cannot_divide_by_zero() -> None:
    reference = pd.Series([0.0] * 100)  # no rain at all in training

    assert drift.drift_score(reference, pd.Series([0.0] * 50)) == 0.0
    assert drift.drift_score(reference, pd.Series([0.5] * 50)) == pytest.approx(500.0)


def test_an_input_with_no_values_is_not_scored() -> None:
    assert drift.drift_score(pd.Series([1.0, 2.0]), pd.Series([np.nan, np.nan])) is None


def test_only_the_inputs_that_moved_drift() -> None:
    rng = np.random.default_rng(1)
    reference = pd.DataFrame({f: rng.normal(10, 2, 2000) for f in drift.DRIFT_FEATURES})
    current = pd.DataFrame({f: rng.normal(10, 2, 500) for f in drift.DRIFT_FEATURES})
    current["raw"] += 3  # the sensors read higher than in training

    results = {f.feature: f for f in drift.compare(reference, current)}

    assert set(results) == set(drift.DRIFT_FEATURES)
    assert "local_hour" not in results  # even over any whole week: never compared
    assert results["raw"].drifted
    assert not results["temperature"].drifted
    assert results["raw"].current_median == pytest.approx(13, abs=0.3)


@pytest.fixture(scope="module")
def sensor_hours(engine: Engine) -> None:
    """Ten days of training-period readings around 10 µg/m³, then a week around 30."""
    training = [START + h * HOUR for h in range(10 * 24)]
    live = [NOW - timedelta(days=7) + h * HOUR for h in range(7 * 24)]
    weather = [WeatherHour(t, 12.0, 75.0, 4.0, 300.0, 0.0) for t in training + live]
    with engine.begin() as connection:
        ids = store.upsert_lowcost_sensors(connection, [SENSOR])
        store.upsert_weather(connection, weather_cell(SENSOR.latitude, SENSOR.longitude), weather)
        readings = [
            LowcostReading(SENSOR.sensor_index, t, base + h % 3, base + 1 + h % 3, 60.0)
            for times, base in ((training, 10.0), (live, 30.0))
            for h, t in enumerate(times)
        ]
        store.upsert_lowcost_readings(connection, readings, ids)


@pytest.mark.usefixtures("sensor_hours")
def test_a_daily_check_finds_the_drift_and_stores_it(engine: Engine) -> None:
    report = drift.build_report(engine, "airsight-correction/99", START, TRAINING_END, NOW)
    drift.store(engine, report)

    assert (report.reference_rows, report.current_rows) == (240, 168)
    assert report.drifted == ["raw"]  # weather and channel difference didn't change
    assert report.share_drifted == pytest.approx(1 / len(drift.DRIFT_FEATURES))
    with engine.connect() as connection:
        stored = connection.execute(
            select(input_drift.c.feature, input_drift.c.drifted).where(
                input_drift.c.checked_at == NOW
            )
        ).all()
    assert dict(stored) == {f: f == "raw" for f in drift.DRIFT_FEATURES}
    assert "1 of 6 inputs drifted" in drift.render_html(report)


@pytest.mark.usefixtures("sensor_hours")
def test_too_few_live_hours_say_so_instead_of_reporting_no_drift(engine: Engine) -> None:
    with pytest.raises(drift.NotEnoughLiveDataError):
        drift.build_report(engine, "airsight-correction/99", START, TRAINING_END, START)


def test_the_check_runs_daily() -> None:
    entry = app.conf.beat_schedule["input-drift"]

    assert entry["task"] == tasks.check_drift.name == "airsight.check_drift"
    assert entry["schedule"] == crontab(minute="15", hour="2")
