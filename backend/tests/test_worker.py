import logging

import pytest
from celery.schedules import crontab
from celery.signals import after_setup_logger

from airsight.ingestion import live
from airsight.ingestion.live import LiveReport
from airsight.worker import tasks
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


def test_worker_logging_hides_request_urls(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)  # like the worker's --loglevel=INFO
    logging.getLogger("httpx2").setLevel(logging.NOTSET)

    after_setup_logger.send(sender=None, logger=logging.getLogger(), loglevel=logging.INFO)

    assert logging.getLogger("httpx2").getEffectiveLevel() >= logging.WARNING
