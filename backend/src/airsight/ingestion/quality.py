"""Data quality: what the per-hour flags mean, and which sensors are healthy enough to use.

Rules come from the data exploration (docs/data-exploration.md). Run a check from backend/:
    uv run python -m airsight.ingestion.quality
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntFlag

from sqlalchemy import Connection, Engine, select, text

from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.core.tables import sensor_health, sensors
from airsight.ingestion import store

logger = logging.getLogger(__name__)


class Flag(IntFlag):
    """Bits of lowcost_readings.flags. PostgreSQL computes them (migration 0002)."""

    MISSING_CHANNEL = 1
    IMPOSSIBLE = 2  # a counter read over 1,000 µg/m³
    STUCK_ZERO = 4  # both counters read exactly zero
    DISAGREE = 8  # counters more than 5 µg/m³ AND more than 70% apart (EPA rule)


# Judge each sensor on recent data, so a repaired sensor comes back and a newly broken one
# is caught. Training data uses the per-hour flags for older history.
WINDOW = timedelta(days=30)
# More impossible hours than this means broken hardware, not occasional spikes
MAX_IMPOSSIBLE_SHARE = 0.10
# A channel missing most hours has stopped, so the other can't be cross-checked (73109)
MAX_MISSING_SHARE = 0.50
# Healthy sensors disagree in at most about 5% of hours, broken ones in 43% or more (#99)
MAX_DISAGREE_SHARE = 0.30
# A sensor whose clean readings sit below NEAR_ZERO while its monitor's median is at least
# REFERENCE_MIN is dead but passes every per-hour check (the San Jose Knox Ave sensor)
NEAR_ZERO = 1.0
REFERENCE_MIN = 3.0

SUMMARY_SQL = """
    WITH nearest AS (
        SELECT DISTINCT ON (lowcost_sensor_id) lowcost_sensor_id, reference_sensor_id
        FROM sensor_pairs
        ORDER BY lowcost_sensor_id, distance_m
    ),
    readings AS (
        SELECT n.lowcost_sensor_id AS sensor_id, l.flags,
               (l.pm25_a + l.pm25_b) / 2 AS raw, r.pm25 AS reference
        FROM nearest n
        JOIN lowcost_readings l ON l.sensor_id = n.lowcost_sensor_id
        LEFT JOIN reference_readings r
            ON r.sensor_id = n.reference_sensor_id AND r.time = l.time
        WHERE l.time >= :start AND l.time < :end
    ),
    summary AS (
        SELECT
            sensor_id,
            count(*) AS hours,
            avg(((flags & 1) <> 0)::int)::real AS missing_share,
            avg(((flags & 2) <> 0)::int)::real AS impossible_share,
            avg(((flags & 8) <> 0)::int)::real AS disagree_share,
            (percentile_cont(0.5) WITHIN GROUP (ORDER BY raw)
                FILTER (WHERE flags = 0 AND reference IS NOT NULL))::real AS median_pm25,
            (percentile_cont(0.5) WITHIN GROUP (ORDER BY reference)
                FILTER (WHERE flags = 0 AND reference IS NOT NULL))::real AS median_reference
        FROM readings
        GROUP BY sensor_id
    )
"""

# The exclusion rule, written once and used by the health table and the training dataset
EXCLUDED_WHEN = """
    impossible_share > :max_impossible
    OR missing_share > :max_missing
    OR disagree_share > :max_disagree
    OR (median_pm25 < :near_zero AND median_reference >= :reference_min)
"""

HEALTH_SQL = text(
    SUMMARY_SQL
    + """
    INSERT INTO sensor_health (
        sensor_id, checked_at, window_start, hours, impossible_share, disagree_share,
        median_pm25, median_reference, status, reason
    )
    SELECT
        sensor_id, :end, :start, hours, impossible_share, disagree_share,
        median_pm25, median_reference,
        CASE WHEN """
    + EXCLUDED_WHEN
    + """ THEN 'excluded' ELSE 'ok' END,
        CASE
            WHEN impossible_share > :max_impossible THEN
                'impossible values in ' || round((impossible_share * 100)::numeric)
                || '% of hours'
            WHEN missing_share > :max_missing THEN
                'a channel missing in ' || round((missing_share * 100)::numeric)
                || '% of hours'
            WHEN disagree_share > :max_disagree THEN
                'channels disagree in ' || round((disagree_share * 100)::numeric)
                || '% of hours'
            WHEN median_pm25 < :near_zero AND median_reference >= :reference_min
                THEN 'reads near zero while its monitor does not'
        END
    FROM summary
"""
)

EXCLUDED_SQL = text(SUMMARY_SQL + "SELECT sensor_id FROM summary WHERE " + EXCLUDED_WHEN)


@dataclass(frozen=True)
class SensorHealth:
    name: str
    source_id: str
    hours: int
    impossible_share: float
    median_pm25: float | None
    median_reference: float | None
    reason: str


def _rule_parameters(start: datetime, end: datetime) -> dict[str, object]:
    return {
        "start": start,
        "end": end,
        "max_impossible": MAX_IMPOSSIBLE_SHARE,
        "max_missing": MAX_MISSING_SHARE,
        "max_disagree": MAX_DISAGREE_SHARE,
        "near_zero": NEAR_ZERO,
        "reference_min": REFERENCE_MIN,
    }


def refresh_sensor_health(connection: Connection, now: datetime) -> int:
    """Recompute sensor_health from the last WINDOW of data. Returns the number excluded."""
    connection.execute(sensor_health.delete())
    connection.execute(HEALTH_SQL, _rule_parameters(now - WINDOW, now))
    return len(excluded_sensors(connection))


def excluded_during(connection: Connection, start: datetime, end: datetime) -> set[int]:
    """Database ids of the sensors the quality rules exclude, judged on [start, end)."""
    rows = connection.execute(EXCLUDED_SQL, _rule_parameters(start, end))
    return set(rows.scalars())


def excluded_sensors(connection: Connection) -> list[SensorHealth]:
    rows = connection.execute(
        select(
            sensors.c.name,
            sensors.c.source_id,
            sensor_health.c.hours,
            sensor_health.c.impossible_share,
            sensor_health.c.median_pm25,
            sensor_health.c.median_reference,
            sensor_health.c.reason,
        )
        .join(sensors, sensors.c.id == sensor_health.c.sensor_id)
        .where(sensor_health.c.status == "excluded")
        .order_by(sensors.c.source_id)
    )
    return [SensorHealth(*row) for row in rows]


def run_quality_check(engine: Engine, now: datetime | None = None) -> list[SensorHealth]:
    """Refresh sensor health, record the run, and log which sensors are excluded."""
    now = now or datetime.now(UTC)
    with engine.begin() as connection:
        run_id = store.start_run(connection, "quality")
    with engine.begin() as connection:
        refresh_sensor_health(connection, now)
        excluded = excluded_sensors(connection)
        checked: int = connection.execute(text("SELECT count(*) FROM sensor_health")).scalar_one()
        store.finish_run(connection, run_id, "succeeded", checked)
    logger.info("Checked %d sensors; %d excluded", checked, len(excluded))
    for sensor in excluded:
        logger.info("Excluded %s (%s): %s", sensor.source_id, sensor.name, sensor.reason)
    return excluded


if __name__ == "__main__":
    configure_logging()
    run_quality_check(get_engine())
