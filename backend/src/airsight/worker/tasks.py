"""Tasks the worker runs. Each one is a thin wrapper around tested ingestion code."""

from dataclasses import asdict

import httpx2
from celery import Task

from airsight.core.db import get_engine
from airsight.ingestion import day_ahead, live, quality
from airsight.ingestion.airnow import AirNowUnavailableError
from airsight.ml import batch, forecast_batch
from airsight.observability import drift
from airsight.worker.celery_app import app

# A network drop on the Mac (Wi-Fi, DNS) outlasts the HTTP client's own retries, which wait
# seconds. Live ingestion then tries again every 10 minutes for 50 minutes, instead of waiting
# 3 hours for its next slot. A retry can spend PurpleAir points again: upserts keep the data
# right, and the points guard still applies.
NETWORK_ERRORS = (httpx2.TransportError, AirNowUnavailableError)
LIVE_RETRIES = 5
LIVE_RETRY_SECONDS = 10 * 60


@app.task(
    name="airsight.ingest_live",
    autoretry_for=NETWORK_ERRORS,
    max_retries=LIVE_RETRIES,
    default_retry_delay=LIVE_RETRY_SECONDS,
)
def ingest_live() -> dict[str, int | bool]:
    """Fetch what's new from AirNow, PurpleAir and Open-Meteo (every 3 hours, ADR 0006)."""
    return asdict(live.run_with_real_clients())


@app.task(name="airsight.check_quality")
def check_quality() -> int:
    """Recompute which sensors are healthy enough to use (daily)."""
    return len(quality.run_quality_check(get_engine()))


@app.task(name="airsight.correct_readings")
def correct_readings() -> int:
    """Recompute the last 48 hours of corrected PM2.5 with the champion model (every 3 hours)."""
    return batch.correct_recent(get_engine())


@app.task(name="airsight.load_day_ahead_weather")
def load_day_ahead_weather() -> int:
    """Reload the last 3 days of day-ahead weather forecasts (daily, ADR 0012)."""
    return day_ahead.load_with_real_client()


# When the laptop wakes, beat starts every overdue job at once, and the forecast can run before
# live ingestion has loaded its issue hour. It waits for the readings instead of reporting an
# empty success: 4 more tries, 15 minutes apart, then the run fails and the dashboard shows it.
# A network error while it fetches the weather forecast is retried the same way.
FORECAST_RETRIES = 4
FORECAST_RETRY_SECONDS = 15 * 60


class NoReadingsYetError(Exception):
    """The issue hour has no clean sensor readings, so there is nothing to forecast from."""


@app.task(
    name="airsight.issue_forecast",
    bind=True,
    autoretry_for=NETWORK_ERRORS,
    max_retries=FORECAST_RETRIES,
    default_retry_delay=FORECAST_RETRY_SECONDS,
)
def issue_forecast(self: "Task[[], int]") -> int:
    """Forecast the next 24 hours for every healthy paired sensor (every 3 hours, ADR 0012)."""
    count = forecast_batch.forecast_latest(get_engine())
    if count == 0:
        raise self.retry(
            exc=NoReadingsYetError("No clean readings at the issue hour yet"),
            countdown=FORECAST_RETRY_SECONDS,
        )
    return count


@app.task(name="airsight.check_drift")
def check_drift() -> int:
    """Compare the last 7 days of model inputs with the training data (daily, ADR 0013)."""
    return drift.check_champion(get_engine())
