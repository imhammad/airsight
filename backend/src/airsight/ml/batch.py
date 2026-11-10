"""Compute corrected PM2.5 with the champion model and store it (ADR 0005, batch predictions).

The worker runs this every 3 hours, after live ingestion. It recomputes the last 48 hours each
time: that picks up weather that arrived late, costs at most about 1,500 rows, and makes a
missed run harmless. The API only ever reads the stored results.

Backfill all history once, from backend/ with the stack up:
    uv run python -m airsight.ml.batch --days 120
"""

import argparse
import logging
from datetime import UTC, datetime, timedelta

import lightgbm as lgb
import mlflow
import pandas as pd
from sqlalchemy import Engine, func, text
from sqlalchemy.dialects.postgresql import insert

from airsight.core.config import get_settings
from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.core.tables import corrected_readings
from airsight.ml.features import INPUT_COLUMNS
from airsight.ml.predict import correct
from airsight.ml.registry import load_champion_version
from airsight.ml.serving import choose_sources

logger = logging.getLogger(__name__)

RECOMPUTE_WINDOW = timedelta(hours=48)
BATCH_ROWS = 5_000

# Clean hours of sensors the quality check hasn't excluded, with the inputs the model needs
INPUTS_SQL = text("""
    SELECT
        l.sensor_id,
        l.time,
        l.pm25_a,
        l.pm25_b,
        l.humidity,
        w.temperature,
        w.relative_humidity,
        w.wind_speed,
        w.precipitation
    FROM lowcost_readings l
    JOIN sensors s ON s.id = l.sensor_id
    LEFT JOIN weather w ON w.cell_id = s.weather_cell_id AND w.time = l.time
    LEFT JOIN sensor_health h ON h.sensor_id = l.sensor_id
    WHERE l.time >= :start AND l.time < :end
      AND l.flags = 0
      AND l.humidity IS NOT NULL
      AND (h.status IS NULL OR h.status <> 'excluded')
    ORDER BY l.sensor_id, l.time
""")


def correct_window(
    engine: Engine, booster: lgb.Booster, model_version: str, start: datetime, end: datetime
) -> int:
    """Correct every clean sensor-hour in [start, end) and upsert it. Returns the row count."""
    with engine.connect() as connection:
        rows = pd.read_sql(INPUTS_SQL, connection, params={"start": start, "end": end})
    if rows.empty:
        return 0
    rows["pm25"] = correct(booster, rows[INPUT_COLUMNS]).clip(lower=0.0)  # no negative PM2.5
    records = [
        {"sensor_id": int(sensor_id), "time": time, "pm25": float(pm25)}
        for sensor_id, time, pm25 in zip(
            rows["sensor_id"].tolist(), rows["time"].tolist(), rows["pm25"].tolist(), strict=True
        )
    ]
    with engine.begin() as connection:
        for first in range(0, len(records), BATCH_ROWS):
            statement = insert(corrected_readings).values(
                [{**r, "model_version": model_version} for r in records[first : first + BATCH_ROWS]]
            )
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=["sensor_id", "time"],
                    set_={
                        "pm25": statement.excluded.pm25,
                        "model_version": statement.excluded.model_version,
                        "computed_at": func.now(),
                    },
                )
            )
    return len(records)


def correct_recent(
    engine: Engine, window: timedelta = RECOMPUTE_WINDOW, now: datetime | None = None
) -> int:
    """Recompute the last `window` of hours with the current champion. The worker's job.

    Then choose each sensor's source again (ml/serving.py), so the choice always reflects the
    corrections just stored.
    """
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    booster, model_version = load_champion_version()
    end = now or datetime.now(UTC)
    count = correct_window(engine, booster, model_version, end - window, end)
    logger.info("Corrected %d sensor-hours with %s", count, model_version)
    choose_sources(engine, model_version, end)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=120, help="how far back to correct")
    args = parser.parse_args()
    configure_logging()
    correct_recent(get_engine(), window=timedelta(days=args.days))


if __name__ == "__main__":
    main()
