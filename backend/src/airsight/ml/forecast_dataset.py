"""Build the versioned forecast dataset (ADR 0012).

One row per sensor, issue hour and hour ahead, with the inputs known at the issue hour and the
paired monitor's reading at the target hour as the label. Weather comes from day_ahead_weather,
never from observed weather. Like the correction dataset, the file is named by a hash of its
contents, so every backtest can record exactly which data it used.

Run from backend/ with the stack up:  uv run python -m airsight.ml.forecast_dataset
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.ingestion.quality import excluded_during
from airsight.ml.dataset import DATASETS_DIR, FINAL_TEST_DAYS, content_hash
from airsight.ml.forecast_features import TARGET, forecast_rows

logger = logging.getLogger(__name__)

# Every hour of every paired sensor; flagged hours keep their place with no raw value
SENSOR_HOURS_SQL = text("""
    WITH nearest AS (
        SELECT DISTINCT ON (lowcost_sensor_id) lowcost_sensor_id, reference_sensor_id
        FROM sensor_pairs
        ORDER BY lowcost_sensor_id, distance_m
    )
    SELECT
        l.sensor_id,
        m.id AS station_id,
        m.name AS station,
        s.weather_cell_id AS cell_id,
        l.time,
        CASE WHEN l.flags = 0 THEN (l.pm25_a + l.pm25_b) / 2 END AS raw
    FROM nearest n
    JOIN sensors s ON s.id = n.lowcost_sensor_id
    JOIN sensors m ON m.id = n.reference_sensor_id
    JOIN lowcost_readings l ON l.sensor_id = n.lowcost_sensor_id
    WHERE l.time >= :start AND l.time < :end
    ORDER BY l.sensor_id, l.time
""")
OFFICIAL_SQL = text("""
    SELECT sensor_id AS station_id, time, pm25 AS official
    FROM reference_readings
    WHERE time >= :start AND time < :end
""")
WEATHER_SQL = text("""
    SELECT cell_id, time, temperature, relative_humidity, wind_speed, wind_direction, precipitation
    FROM day_ahead_weather
    WHERE time >= :start AND time < :end
""")


@dataclass(frozen=True)
class ForecastDatasetInfo:
    path: str
    content_hash: str
    start: str
    end: str
    final_test_start: str
    rows: int
    issues: int
    sensors: int
    stations: int
    excluded_sensors: list[int]


def load_forecast_rows(
    engine: Engine, start: datetime, end: datetime
) -> tuple[pd.DataFrame, set[int]]:
    """Labelled forecast rows for issue hours in [start, end), and the sensors left out."""
    params = {"start": start, "end": end}
    with engine.connect() as connection:
        excluded = excluded_during(connection, start, end)
        sensor_hours = pd.read_sql(SENSOR_HOURS_SQL, connection, params=params)
        official = pd.read_sql(OFFICIAL_SQL, connection, params=params)
        weather = pd.read_sql(WEATHER_SQL, connection, params=params)
    sensor_hours = sensor_hours[~sensor_hours["sensor_id"].isin(excluded)]
    rows = forecast_rows(sensor_hours, official, weather, start, end)
    return rows[rows[TARGET].notna()].reset_index(drop=True), excluded


def build_forecast_dataset(
    engine: Engine, start: datetime, end: datetime, out_dir: Path = DATASETS_DIR
) -> ForecastDatasetInfo:
    """Write the dataset as Parquet plus a JSON description, both named by the content hash."""
    frame, excluded = load_forecast_rows(engine, start, end)
    digest = content_hash(frame)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"forecast-{digest}.parquet"
    frame.to_parquet(path, index=False)
    info = ForecastDatasetInfo(
        path=str(path),
        content_hash=digest,
        start=start.isoformat(),
        end=end.isoformat(),
        final_test_start=(end - timedelta(days=FINAL_TEST_DAYS)).isoformat(),
        rows=len(frame),
        issues=int(frame[["sensor_id", "issue_time"]].drop_duplicates().shape[0]),
        sensors=int(frame["sensor_id"].nunique()),
        stations=int(frame["station_id"].nunique()),
        excluded_sensors=sorted(excluded),
    )
    path.with_suffix(".json").write_text(json.dumps(asdict(info), indent=2) + "\n")
    return info


def main() -> None:
    configure_logging()
    engine = get_engine()
    with engine.connect() as connection:
        first = connection.execute(text("SELECT min(time) FROM day_ahead_weather")).scalar_one()
    # Whole days only, so rebuilding later the same day gives the same data
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = first.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    info = build_forecast_dataset(engine, start, end)
    logger.info(
        "Forecast dataset %s: %d rows, %d issues, %d sensors, %d stations",
        info.content_hash,
        info.rows,
        info.issues,
        info.sensors,
        info.stations,
    )
    logger.info("Final test period starts %s; written to %s", info.final_test_start, info.path)


if __name__ == "__main__":
    main()
