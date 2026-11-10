"""Choose, station by station, whether sensors show corrected or raw readings (ADR 0010).

A correction model can drift. After every correction run, each official monitor's last 14 days
are scored: where the champion's corrections were further from the monitor than the sensors'
own readings, over at least 200 scored hours, the sensors paired with that monitor show raw.
When the correction wins again, they switch back on the next run.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, delete, insert, text

from airsight.core.tables import serving_sources

logger = logging.getLogger(__name__)

WINDOW = timedelta(days=14)
MIN_HOURS = 200  # fewer scored hours than this is too little evidence to switch

# Each sensor's nearest official monitor (the pairing the training data and /v1/accuracy use),
# with that monitor's scores over the window. Monitors with no scored hours get nulls.
SCORES_SQL = text("""
    WITH nearest AS (
        SELECT DISTINCT ON (lowcost_sensor_id) lowcost_sensor_id, reference_sensor_id
        FROM sensor_pairs
        ORDER BY lowcost_sensor_id, distance_m
    ),
    scores AS (
        SELECT
            n.reference_sensor_id AS station_id,
            count(*) AS hours,
            avg(abs(c.pm25 - r.pm25)) AS corrected_mae,
            avg(abs((l.pm25_a + l.pm25_b) / 2 - r.pm25)) AS raw_mae
        FROM corrected_readings c
        JOIN nearest n ON n.lowcost_sensor_id = c.sensor_id
        JOIN reference_readings r ON r.sensor_id = n.reference_sensor_id AND r.time = c.time
        JOIN lowcost_readings l ON l.sensor_id = c.sensor_id AND l.time = c.time
        WHERE c.time >= :start AND c.time < :end
          AND c.model_version = :model_version
          AND l.pm25_a IS NOT NULL AND l.pm25_b IS NOT NULL
        GROUP BY n.reference_sensor_id
    )
    SELECT
        n.lowcost_sensor_id AS sensor_id,
        n.reference_sensor_id AS station_id,
        COALESCE(s.hours, 0) AS hours,
        s.corrected_mae,
        s.raw_mae
    FROM nearest n
    LEFT JOIN scores s ON s.station_id = n.reference_sensor_id
    ORDER BY n.lowcost_sensor_id
""")


@dataclass(frozen=True)
class Choice:
    sensor_id: int
    station_id: int
    source: str
    hours: int
    corrected_mae: float | None
    raw_mae: float | None


def choose(hours: int, corrected_mae: float | None, raw_mae: float | None) -> str:
    """raw only with enough evidence that the correction is worse; corrected otherwise."""
    if hours >= MIN_HOURS and corrected_mae is not None and raw_mae is not None:
        return "raw" if corrected_mae > raw_mae else "corrected"
    return "corrected"


def choose_sources(engine: Engine, model_version: str, now: datetime) -> list[Choice]:
    """Score every monitor over the last WINDOW and store each served sensor's choice."""
    end = now.replace(minute=0, second=0, microsecond=0)
    with engine.begin() as connection:
        rows = connection.execute(
            SCORES_SQL, {"start": end - WINDOW, "end": end, "model_version": model_version}
        ).mappings()
        choices = [
            Choice(
                sensor_id=row["sensor_id"],
                station_id=row["station_id"],
                source=choose(row["hours"], row["corrected_mae"], row["raw_mae"]),
                hours=row["hours"],
                corrected_mae=row["corrected_mae"],
                raw_mae=row["raw_mae"],
            )
            for row in rows
        ]
        # Replace every row in one transaction, so readers see the old choices or the new ones
        connection.execute(delete(serving_sources))
        if choices:
            connection.execute(
                insert(serving_sources),
                [
                    {**vars(choice), "model_version": model_version, "decided_at": now}
                    for choice in choices
                ],
            )
    raw = sorted({c.station_id for c in choices if c.source == "raw"})
    logger.info("%d sensors chose a source; monitors showing raw: %s", len(choices), raw or "none")
    return choices
