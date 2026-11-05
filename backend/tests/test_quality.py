from datetime import UTC, datetime, timedelta

import pytest
from celery.schedules import crontab
from sqlalchemy import Engine, select

from airsight.core.tables import lowcost_readings, sensor_health
from airsight.ingestion import store
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ingestion.quality import Flag, run_quality_check
from airsight.worker.celery_app import app

# A made-up monitor near Livermore, away from the other tests' sensors
MONITOR = (37.5000, -121.7000)
SEEN = datetime(2026, 8, 1, tzinfo=UTC)
HEALTHY = Sensor(900201, "Healthy", 37.5030, -121.7000, SEEN)
BROKEN = Sensor(900202, "Broken", 37.5000, -121.7040, SEEN)
DEAD = Sensor(900203, "Dead", 37.4970, -121.7000, SEEN)
NOW = datetime(2026, 9, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.mark.parametrize(
    ("pm25_a", "pm25_b", "expected"),
    [
        (8.0, 8.5, Flag(0)),
        (8.0, None, Flag.MISSING_CHANNEL),
        (5000.0, 0.0, Flag.IMPOSSIBLE | Flag.DISAGREE),
        (0.0, 0.0, Flag.STUCK_ZERO),
        (2.0, 20.0, Flag.DISAGREE),
        (40.0, 46.0, Flag(0)),  # 6 apart, but only 14%: fine
    ],
)
def test_flags_are_computed_by_the_database(
    engine: Engine, pm25_a: float, pm25_b: float | None, expected: Flag
) -> None:
    with engine.begin() as connection:
        ids = store.upsert_lowcost_sensors(connection, [HEALTHY])
        store.upsert_lowcost_readings(
            connection,
            [LowcostReading(HEALTHY.sensor_index, SEEN, pm25_a, pm25_b, 50.0)],
            ids,
        )
        flags = connection.execute(
            select(lowcost_readings.c.flags).where(
                lowcost_readings.c.sensor_id == ids[HEALTHY.sensor_index],
                lowcost_readings.c.time == SEEN,
            )
        ).scalar_one()

    assert Flag(flags) == expected


def lowcost_value(sensor: Sensor, hour: int) -> tuple[float, float]:
    if sensor is BROKEN and hour % 5 == 0:  # 20% of hours
        return 5000.0, 0.0
    if sensor is DEAD:
        return 0.1, 0.1
    return 8.0, 8.4


@pytest.fixture(scope="module")
def thirty_days(engine: Engine) -> None:
    """One monitor reading 8 µg/m³ with a healthy, a broken and a dead sensor nearby."""
    hours = [NOW - timedelta(days=30) + h * HOUR for h in range(30 * 24)]
    reference = [ReferenceReading("QUAL0001", "Quality monitor", *MONITOR, t, 8.0) for t in hours]
    with engine.begin() as connection:
        station_ids = store.upsert_reference_stations(connection, reference)
        store.upsert_reference_readings(connection, reference, station_ids)
        ids = store.upsert_lowcost_sensors(connection, [HEALTHY, BROKEN, DEAD])
        store.refresh_sensor_pairs(connection, 1000.0)
        for sensor in (HEALTHY, BROKEN, DEAD):
            readings = [
                LowcostReading(sensor.sensor_index, t, *lowcost_value(sensor, h), 50.0)
                for h, t in enumerate(hours)
            ]
            store.upsert_lowcost_readings(connection, readings, ids)


def test_broken_and_dead_sensors_are_excluded(engine: Engine, thirty_days: None) -> None:
    excluded = run_quality_check(engine, now=NOW)

    reasons = {sensor.source_id: sensor.reason for sensor in excluded}
    assert reasons == {
        "900202": "impossible values in 20% of hours",
        "900203": "reads near zero while its monitor does not",
    }


def test_healthy_sensor_is_ok(engine: Engine, thirty_days: None) -> None:
    run_quality_check(engine, now=NOW)

    with engine.connect() as connection:
        statuses = connection.execute(select(sensor_health.c.status)).scalars().all()
    assert statuses.count("ok") == 1


def test_quality_check_runs_daily() -> None:
    entry = app.conf.beat_schedule["quality-check"]

    assert entry["task"] == "airsight.check_quality"
    assert entry["schedule"] == crontab(minute="45", hour="1")
    assert "airsight.check_quality" in app.tasks
