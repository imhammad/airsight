import logging
from collections.abc import Iterator

import httpx2
import pytest
from celery.exceptions import Retry
from celery.schedules import crontab
from celery.signals import setup_logging, task_postrun, task_prerun

from airsight.core.logging import HANDLER_NAME, JsonFormatter, current_task
from airsight.ingestion import live
from airsight.ingestion.airnow import AirNowError, AirNowUnavailableError
from airsight.ingestion.live import LiveReport
from airsight.ml import forecast_batch
from airsight.worker import runs, tasks
from airsight.worker.celery_app import app


def test_live_ingestion_is_scheduled_every_three_hours() -> None:
    entry = app.conf.beat_schedule["live-ingestion"]

    assert entry["task"] == "airsight.ingest_live"
    assert entry["schedule"] == crontab(minute="15", hour="0,3,6,9,12,15,18,21")


def test_day_ahead_weather_is_loaded_daily() -> None:
    entry = app.conf.beat_schedule["day-ahead-weather"]

    assert entry["task"] == "airsight.load_day_ahead_weather"
    assert entry["schedule"] == crontab(minute="45", hour="4")
    assert tasks.load_day_ahead_weather.name == "airsight.load_day_ahead_weather"


def test_the_scheduled_task_is_registered() -> None:
    assert "airsight.ingest_live" in app.tasks


def test_task_runs_live_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    report = LiveReport(reference_rows=60, lowcost_rows=40, weather_rows=72, points_spent=242)
    monkeypatch.setattr(live, "run_with_real_clients", lambda: report)

    result = tasks.ingest_live()

    assert result["lowcost_rows"] == 40
    assert result["points_spent"] == 242


def test_worker_logs_json_and_hides_request_urls() -> None:
    logging.getLogger("httpx2").setLevel(logging.NOTSET)

    # What Celery sends at start-up, with the worker's --loglevel=INFO
    setup_logging.send(sender=None, loglevel=logging.INFO, logfile=None, format="", colorize=False)

    ours = [h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME]
    assert len(ours) == 1
    assert isinstance(ours[0].formatter, JsonFormatter)
    assert logging.getLogger("httpx2").getEffectiveLevel() >= logging.WARNING


def test_lines_logged_during_a_task_name_it() -> None:
    task = app.tasks["airsight.ingest_live"]

    task_prerun.send(sender=task, task_id="abc-123", task=task, args=(), kwargs={})
    during = current_task.get()
    task_postrun.send(sender=task, task_id="abc-123", task=task, args=(), kwargs={}, retval=None)

    assert during == ("airsight.ingest_live", "abc-123")
    assert current_task.get() is None


class FakeForecast:
    """Stands in for forecast_latest: returns the given hour counts in turn and counts its calls."""

    def __init__(self, counts: Iterator[int]) -> None:
        self.counts = counts
        self.calls = 0

    def __call__(self, engine: object) -> int:
        self.calls += 1
        return next(self.counts)


@pytest.fixture
def no_run_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "get_engine", lambda: None)
    monkeypatch.setattr(runs, "record_start", lambda *_: None)
    monkeypatch.setattr(runs, "record_finish", lambda *_: None)


@pytest.mark.usefixtures("no_run_records")
def test_the_forecast_waits_for_the_readings_after_a_wake_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The first two tries run before live ingestion has loaded the issue hour
    forecast = FakeForecast(iter([0, 0, 720]))
    monkeypatch.setattr(forecast_batch, "forecast_latest", forecast)

    result = tasks.issue_forecast.apply()

    assert result.get() == 720
    assert forecast.calls == 3


@pytest.mark.usefixtures("no_run_records")
def test_the_forecast_fails_when_the_readings_never_come(monkeypatch: pytest.MonkeyPatch) -> None:
    forecast = FakeForecast(iter([0] * 10))
    monkeypatch.setattr(forecast_batch, "forecast_latest", forecast)

    result = tasks.issue_forecast.apply()

    assert result.failed()
    assert isinstance(result.result, tasks.NoReadingsYetError)
    assert forecast.calls == 1 + tasks.FORECAST_RETRIES
    assert tasks.FORECAST_RETRIES * tasks.FORECAST_RETRY_SECONDS == 60 * 60  # gives up after 1 hour


def test_a_retried_attempt_is_recorded_with_its_reason() -> None:
    assert runs.error_name(Retry(exc=tasks.NoReadingsYetError())) == "NoReadingsYetError"
    assert runs.error_name(Retry()) == "Retry"
    assert runs.error_name(RuntimeError("no weather")) == "RuntimeError"


class FlakyLive:
    """Stands in for live ingestion: raises the given errors in turn, then reports success."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self) -> LiveReport:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return LiveReport(reference_rows=60, lowcost_rows=40, weather_rows=72, points_spent=242)


@pytest.mark.usefixtures("no_run_records")
def test_live_ingestion_tries_again_after_a_network_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    flaky = FlakyLive(
        AirNowUnavailableError("AirNow request failed: ConnectError"),
        httpx2.ConnectError("[Errno -2] Name or service not known"),
    )
    monkeypatch.setattr(live, "run_with_real_clients", flaky)

    result = tasks.ingest_live.apply()

    assert result.get()["lowcost_rows"] == 40
    assert flaky.calls == 3


@pytest.mark.usefixtures("no_run_records")
def test_live_ingestion_gives_up_after_50_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    flaky = FlakyLive(*[AirNowUnavailableError("down")] * 10)
    monkeypatch.setattr(live, "run_with_real_clients", flaky)

    result = tasks.ingest_live.apply()

    assert result.failed()
    assert flaky.calls == 1 + tasks.LIVE_RETRIES
    assert tasks.LIVE_RETRIES * tasks.LIVE_RETRY_SECONDS == 50 * 60


@pytest.mark.usefixtures("no_run_records")
def test_live_ingestion_does_not_retry_a_rejected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # A bad key fails the same way every time, so retrying would only spend points
    flaky = FlakyLive(AirNowError("AirNow returned HTTP 401"))
    monkeypatch.setattr(live, "run_with_real_clients", flaky)

    result = tasks.ingest_live.apply()

    assert result.failed()
    assert flaky.calls == 1


@pytest.mark.usefixtures("no_run_records")
def test_the_forecast_tries_again_when_the_weather_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forecast(engine: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx2.ConnectError("[Errno -2] Name or service not known")
        return 720

    monkeypatch.setattr(forecast_batch, "forecast_latest", forecast)

    result = tasks.issue_forecast.apply()

    assert result.get() == 720
    assert calls == 2
