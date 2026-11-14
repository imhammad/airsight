"""Keep the database up to date. The worker runs this every 3 hours (ADR 0004, ADR 0006).

Run once by hand, from backend/:  uv run python -m airsight.ingestion.live
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

from airsight.core.config import get_settings
from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.ingestion import steps, store
from airsight.ingestion.airnow import AirNowClient
from airsight.ingestion.http_client import create_client
from airsight.ingestion.open_meteo import OpenMeteoClient
from airsight.ingestion.purpleair import PointsBudget, PurpleAirClient
from airsight.ingestion.steps import LowcostSource, ReferenceSource, WeatherSource

logger = logging.getLogger(__name__)

# AirNow publishes some hours late and revises recent ones, and it costs nothing to ask again
REFERENCE_LOOKBACK = timedelta(hours=6)
# After an outage (ours or AirNow's), go back to the newest stored hour, up to 3 days: one
# request per day, and AirNow charges nothing
MAX_REFERENCE_CATCH_UP = timedelta(days=3)
# A sensor with no readings yet gets the same window as one normal run
FIRST_WINDOW = timedelta(hours=3)
# After an outage, catch up at most one day per sensor so one run can't drain the points
MAX_CATCH_UP = timedelta(hours=24)
# A normal run costs about 500 points; catching up a full day costs about 4,000
POINTS_PER_RUN = 5_000
# Any fixed number works: it names the PostgreSQL lock that stops two runs overlapping
LOCK_ID = 2_026_110_434


@dataclass
class LiveReport:
    reference_rows: int = 0
    lowcost_rows: int = 0
    weather_rows: int = 0
    points_spent: int = 0
    skipped: bool = False

    @property
    def total_rows(self) -> int:
        return self.reference_rows + self.lowcost_rows + self.weather_rows


def start_of_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def reference_window(latest: datetime | None, end: datetime) -> datetime:
    """Where the AirNow request starts: the last 6 hours, or further back to fill a gap."""
    if latest is None:
        return end - REFERENCE_LOOKBACK
    return max(
        min(latest + timedelta(hours=1), end - REFERENCE_LOOKBACK), end - MAX_REFERENCE_CATCH_UP
    )


def lowcost_window(latest: datetime | None, end: datetime) -> datetime:
    """Where a sensor's next request starts: right after its newest stored hour."""
    if latest is None:
        return end - FIRST_WINDOW
    return max(latest + timedelta(hours=1), end - MAX_CATCH_UP)


def ingest_recent(
    engine: Engine,
    reference: ReferenceSource,
    lowcost: LowcostSource,
    weather: WeatherSource,
    end: datetime,
) -> LiveReport:
    """Load the hours each source is missing, up to end (exclusive). Every write is an upsert."""
    report = LiveReport()

    with engine.connect() as connection:
        reference_start = reference_window(store.latest_reference_time(connection), end)
        paired = store.paired_lowcost_sensors(connection)
        latest = store.latest_lowcost_times(connection)
    report.reference_rows = steps.load_reference(engine, reference, reference_start, end)

    earliest = reference_start
    for sensor_index, sensor_id in paired.items():
        start = lowcost_window(latest.get(sensor_id), end)
        if start >= end:
            continue  # already up to date: don't spend points
        earliest = min(earliest, start)
        report.lowcost_rows += steps.load_lowcost(
            engine, lowcost, sensor_index, sensor_id, start, end
        )

    report.weather_rows = steps.load_weather(engine, weather, earliest, end)
    steps.refresh_hourly(engine, earliest, end)

    report.points_spent = lowcost.budget.spent
    return report


def run_live_ingestion(
    engine: Engine,
    reference: ReferenceSource,
    lowcost: LowcostSource,
    weather: WeatherSource,
    now: datetime | None = None,
) -> LiveReport:
    """One live run: skipped if another run holds the lock, recorded in ingestion_runs."""
    end = start_of_hour(now or datetime.now(UTC))
    # The lock belongs to this connection and is released when we unlock or the connection dies
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock:
        acquired = lock.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID})
        if not acquired.scalar_one():
            logger.warning("Another live ingestion run is still going; skipping this one")
            return LiveReport(skipped=True)
        try:
            with engine.begin() as connection:
                run_id = store.start_run(connection, "live")
            try:
                report = ingest_recent(engine, reference, lowcost, weather, end)
            except Exception as error:
                with engine.begin() as connection:
                    store.finish_run(connection, run_id, "failed", 0, type(error).__name__)
                raise
            with engine.begin() as connection:
                store.finish_run(connection, run_id, "succeeded", report.total_rows)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    logger.info("Live ingestion done: %s", report)
    return report


def run_with_real_clients() -> LiveReport:
    """One live run against the real APIs and database. The worker calls this."""
    settings = get_settings()
    if settings.airnow_key is None or settings.purpleair_key is None:
        raise RuntimeError("AIRNOW_KEY and PURPLEAIR_KEY must be set (see .env.example)")
    with create_client(settings.http_timeout_seconds) as http:
        return run_live_ingestion(
            get_engine(),
            AirNowClient(http, settings.airnow_key),
            PurpleAirClient(http, settings.purpleair_key, PointsBudget(POINTS_PER_RUN)),
            OpenMeteoClient(http),
        )


if __name__ == "__main__":
    configure_logging()
    run_with_real_clients()
