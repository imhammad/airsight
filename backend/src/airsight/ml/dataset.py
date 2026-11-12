"""Build the versioned training dataset (ADR 0007).

One row per clean sensor-hour, paired with the nearest official monitor's reading for the same
hour, plus weather and time features. The file is named by a hash of its contents, so every
experiment can record exactly which data it used.

Run from backend/:  uv run python -m airsight.ml.dataset
"""

import hashlib
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
from airsight.ml.features import add_features

logger = logging.getLogger(__name__)

# ADR 0007: the last 14 days are the final test period, scored once per release
FINAL_TEST_DAYS = 14
DATASETS_DIR = Path("../data/datasets")  # the repo's data/ folder, git-ignored

PAIRS_SQL = text("""
    WITH nearest AS (
        SELECT DISTINCT ON (lowcost_sensor_id) lowcost_sensor_id, reference_sensor_id
        FROM sensor_pairs
        ORDER BY lowcost_sensor_id, distance_m
    )
    SELECT
        l.sensor_id,
        m.id AS station_id,
        m.name AS station,
        l.time,
        l.pm25_a,
        l.pm25_b,
        l.humidity,
        w.temperature,
        w.relative_humidity,
        w.wind_speed,
        w.precipitation,
        r.pm25 AS official
    FROM nearest n
    JOIN sensors s ON s.id = n.lowcost_sensor_id
    JOIN sensors m ON m.id = n.reference_sensor_id
    JOIN lowcost_readings l ON l.sensor_id = n.lowcost_sensor_id
    JOIN reference_readings r ON r.sensor_id = n.reference_sensor_id AND r.time = l.time
    LEFT JOIN weather w ON w.cell_id = s.weather_cell_id AND w.time = l.time
    WHERE l.time >= :start AND l.time < :end
      AND l.flags = 0
      AND l.humidity IS NOT NULL  -- needed by the EPA baseline
    ORDER BY l.sensor_id, l.time
""")


@dataclass(frozen=True)
class DatasetInfo:
    path: str
    content_hash: str
    start: str
    end: str
    final_test_start: str
    rows: int
    sensors: int
    stations: int
    excluded_sensors: list[int]


def load_pairs(engine: Engine, start: datetime, end: datetime) -> tuple[pd.DataFrame, set[int]]:
    """Clean paired sensor-hours in [start, end) with features, and the sensors left out."""
    with engine.connect() as connection:
        excluded = excluded_during(connection, start, end)
        frame = pd.read_sql(PAIRS_SQL, connection, params={"start": start, "end": end})
    frame = frame[~frame["sensor_id"].isin(excluded)].reset_index(drop=True)
    return add_features(frame), excluded


def content_hash(frame: pd.DataFrame) -> str:
    """The same rows and values always give the same hash, whatever the file's bytes."""
    row_hashes = pd.util.hash_pandas_object(frame, index=False).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()[:12]


def build_dataset(
    engine: Engine, start: datetime, end: datetime, out_dir: Path = DATASETS_DIR
) -> DatasetInfo:
    """Write the dataset as Parquet plus a JSON description, both named by the content hash."""
    frame, excluded = load_pairs(engine, start, end)
    digest = content_hash(frame)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pairs-{digest}.parquet"
    frame.to_parquet(path, index=False)
    info = DatasetInfo(
        path=str(path),
        content_hash=digest,
        start=start.isoformat(),
        end=end.isoformat(),
        final_test_start=(end - timedelta(days=FINAL_TEST_DAYS)).isoformat(),
        rows=len(frame),
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
        first = connection.execute(text("SELECT min(time) FROM lowcost_readings")).scalar_one()
    # Whole days only, so rebuilding later the same day gives the same data
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = first.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    info = build_dataset(engine, start, end)
    logger.info(
        "Dataset %s: %d rows, %d sensors, %d stations",
        info.content_hash,
        info.rows,
        info.sensors,
        info.stations,
    )
    logger.info("Final test period starts %s; written to %s", info.final_test_start, info.path)


if __name__ == "__main__":
    main()
