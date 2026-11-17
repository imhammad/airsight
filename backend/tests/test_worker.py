import logging

import pytest
from celery.schedules import crontab
from celery.signals import setup_logging, task_postrun, task_prerun

from airsight.core.logging import HANDLER_NAME, JsonFormatter, current_task
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
