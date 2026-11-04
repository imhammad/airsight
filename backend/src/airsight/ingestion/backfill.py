"""Load historical data for the training region.

Run from backend/:  uv run python -m airsight.ingestion.backfill --days 7
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from airsight.core.config import get_settings
from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.ingestion import steps, store
from airsight.ingestion.airnow import AirNowClient
from airsight.ingestion.http_client import create_client
from airsight.ingestion.open_meteo import OpenMeteoClient
from airsight.ingestion.purpleair import PointsBudget, PurpleAirClient
from airsight.ingestion.regions import around
from airsight.ingestion.steps import LowcostSource, ReferenceSource, WeatherSource

logger = logging.getLogger(__name__)

PAIR_DISTANCE_M = 1000.0  # ADR 0006: only sensors within 1 km of a monitor
SEARCH_KM = 1.5  # search a little wider; PostGIS then applies the exact distance
MAX_DAYS = 90  # Open-Meteo returns at most 92 past days from its forecast API


@dataclass
class BackfillReport:
    reference_rows: int = 0
    stations: int = 0
    paired_sensors: int = 0
    lowcost_rows: int = 0
    weather_rows: int = 0
    points_spent: int = 0

    @property
    def total_rows(self) -> int:
        return self.reference_rows + self.lowcost_rows + self.weather_rows


def backfill(
    engine: Engine,
    reference: ReferenceSource,
    lowcost: LowcostSource,
    weather: WeatherSource,
    start: datetime,
    end: datetime,
) -> BackfillReport:
    """Load [start, end) for every source. Safe to run again: every write is an upsert."""
    report = BackfillReport()

    # 1. Official monitors
    report.reference_rows = steps.load_reference(engine, reference, start, end)
    logger.info("Official monitors: %d hourly readings", report.reference_rows)

    # 2. Low-cost sensors near each monitor (small searches cost far fewer points)
    with engine.begin() as connection:
        stations = store.reference_locations(connection)
        report.stations = len(stations)
        found = [
            sensor
            for latitude, longitude in stations
            for sensor in lowcost.sensors(around(latitude, longitude, SEARCH_KM), max_sensors=200)
        ]
        store.upsert_lowcost_sensors(connection, found)
        store.refresh_sensor_pairs(connection, PAIR_DISTANCE_M)
        paired = store.paired_lowcost_sensors(connection)
    report.paired_sensors = len(paired)
    logger.info("%d monitors, %d sensors within 1 km", report.stations, report.paired_sensors)

    # 3. Hourly history for each paired sensor, only for the hours before its oldest stored
    #    hour: a longer backfill doesn't pay again for recent hours, and a rerun after a
    #    failure resumes where it stopped (each sensor is loaded in one transaction)
    with engine.connect() as connection:
        oldest = store.earliest_lowcost_times(connection)
    for number, (sensor_index, sensor_id) in enumerate(paired.items(), start=1):
        sensor_end = min(end, oldest.get(sensor_id, end))
        if sensor_end <= start:
            logger.info("Sensor %d/%d: already loaded", number, len(paired))
            continue
        rows = steps.load_lowcost(engine, lowcost, sensor_index, sensor_id, start, sensor_end)
        report.lowcost_rows += rows
        logger.info("Sensor %d/%d: %d hours", number, len(paired), rows)

    # 4. Weather for every cell in use
    report.weather_rows = steps.load_weather(engine, weather, start, end)
    logger.info("Weather: %d cell-hours", report.weather_rows)

    # 5. Hourly averages for the loaded range
    steps.refresh_hourly(engine, start, end)

    report.points_spent = lowcost.budget.spent
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, required=True, help=f"days to load, 1 to {MAX_DAYS}")
    parser.add_argument(
        "--points-budget",
        type=int,
        default=50_000,
        help="maximum PurpleAir points this run may spend (default 50,000)",
    )
    args = parser.parse_args()
    if not 1 <= args.days <= MAX_DAYS:
        parser.error(f"--days must be between 1 and {MAX_DAYS}")

    configure_logging()
    settings = get_settings()
    if settings.airnow_key is None or settings.purpleair_key is None:
        raise SystemExit("AIRNOW_KEY and PURPLEAIR_KEY must be set (see .env.example)")

    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    engine = get_engine()
    with create_client(settings.http_timeout_seconds) as http:
        sources = (
            AirNowClient(http, settings.airnow_key),
            PurpleAirClient(http, settings.purpleair_key, PointsBudget(args.points_budget)),
            OpenMeteoClient(http),
        )
        with engine.begin() as connection:
            run_id = store.start_run(connection, f"backfill {args.days}d")
        try:
            report = backfill(engine, *sources, start=start, end=end)
        except Exception as error:
            with engine.begin() as connection:
                store.finish_run(connection, run_id, "failed", 0, type(error).__name__)
            raise
        with engine.begin() as connection:
            store.finish_run(connection, run_id, "succeeded", report.total_rows)

    logger.info("Done: %s", report)


if __name__ == "__main__":
    main()
