"""Load day-ahead weather forecasts for every weather cell in use (ADR 0012).

The air quality forecast trains on these, never on the weather that actually happened. The
worker keeps the last few days up to date; this command also fills in the history.

Run from backend/:  uv run python -m airsight.ingestion.day_ahead            (all our history)
                    uv run python -m airsight.ingestion.day_ahead --days 3   (the last 3 days)
"""

import argparse
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

from airsight.core.config import get_settings
from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.ingestion.http_client import create_client
from airsight.ingestion.open_meteo import OpenMeteoClient
from airsight.ingestion.steps import DayAheadWeatherSource, load_day_ahead_weather

logger = logging.getLogger(__name__)

RECENT_DAYS = 3  # what the daily job reloads: enough to cover a missed day or two


def load(
    engine: Engine, source: DayAheadWeatherSource, now: datetime, days: int | None = None
) -> int:
    """Day-ahead weather up to the last complete hour: the last `days` days, or all history."""
    end = now.replace(minute=0, second=0, microsecond=0)
    if days is not None:
        start = end - timedelta(days=days)
    else:
        with engine.connect() as connection:
            first = connection.execute(text("SELECT min(time) FROM lowcost_readings")).scalar()
        if first is None:
            return 0  # nothing to forecast yet
        start = first.replace(minute=0, second=0, microsecond=0)
    return load_day_ahead_weather(engine, source, start, end)


def load_with_real_client(days: int | None = RECENT_DAYS) -> int:
    """One load against the real Open-Meteo API and database. The worker calls this."""
    with create_client(get_settings().http_timeout_seconds) as http:
        return load(get_engine(), OpenMeteoClient(http), datetime.now(UTC), days)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, help="only the last N days (default: all history)")
    args = parser.parse_args()
    configure_logging()
    rows = load_with_real_client(args.days)
    logger.info("Day-ahead weather: %d cell-hours", rows)


if __name__ == "__main__":
    main()
