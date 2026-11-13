"""The Celery app. Start it from backend/ with:

uv run celery -A airsight.worker.celery_app worker --loglevel=INFO
uv run celery -A airsight.worker.celery_app beat --loglevel=INFO
"""

from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import after_setup_logger, after_setup_task_logger

from airsight.core.config import get_settings
from airsight.core.logging import quiet_request_logs

app = Celery("airsight", broker=get_settings().redis_url, include=["airsight.worker.tasks"])

app.conf.update(
    timezone="UTC",
    # Results are recorded in ingestion_runs, so Celery doesn't need to store them
    task_ignore_result=True,
    # Take one task at a time, and confirm it only after it finishes: if the worker
    # dies mid-run, Redis hands the task out again
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # A run normally takes about a minute; anything near an hour is stuck
    task_soft_time_limit=50 * 60,
    task_time_limit=60 * 60,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "live-ingestion": {
            "task": "airsight.ingest_live",
            # 00:15, 03:15, 06:15 ... UTC: a quarter past, so AirNow has published the hour
            "schedule": crontab(minute="15", hour="*/3"),
            # If the worker was down, drop the old run: the next one catches up anyway
            "options": {"expires": 2 * 60 * 60},
        },
        "correct-readings": {
            "task": "airsight.correct_readings",
            # 15 minutes after each live ingestion, which normally takes about a minute
            "schedule": crontab(minute="30", hour="*/3"),
            "options": {"expires": 2 * 60 * 60},
        },
        "issue-forecast": {
            "task": "airsight.issue_forecast",
            # 15 minutes after each correction run, so it forecasts from the hour just ingested
            "schedule": crontab(minute="45", hour="*/3"),
            "options": {"expires": 2 * 60 * 60},
        },
        "quality-check": {
            "task": "airsight.check_quality",
            # Once a day, between live runs
            "schedule": crontab(minute="45", hour="1"),
        },
        "day-ahead-weather": {
            "task": "airsight.load_day_ahead_weather",
            # Once a day, between live runs; a missed day is reloaded the next day
            "schedule": crontab(minute="45", hour="4"),
        },
    },
)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _quiet_request_logs(**_: Any) -> None:
    """Celery sets up its own logging, so the AirNow key protection must be applied again."""
    quiet_request_logs()
