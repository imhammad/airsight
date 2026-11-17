"""Pipeline and model metrics for Prometheus, read from the database (ADR 0013).

Run it with `python -m airsight.observability.exporter`; it serves /metrics on port 9108.
Every number comes from what the jobs left behind, so a worker that has stopped shows up as
data getting old, never as a healthy worker that simply has nothing to say.
"""

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import redis
from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from sqlalchemy import Engine, text

from airsight.api import accuracy, forecast_accuracy
from airsight.api.champion import load_champion_info
from airsight.api.schemas import ModelInfo
from airsight.core.config import get_settings
from airsight.core.db import get_engine
from airsight.core.logging import configure_logging

logger = logging.getLogger(__name__)

PORT = 9108
QUEUE = "celery"  # Celery's default queue: a Redis list of waiting tasks
# The accuracy windows of the public accuracy page (routes/model.py)
CORRECTION_DAYS = 14
FORECAST_DAYS = 7
# Accuracy changes at most every 3 hours, and its queries join two weeks of readings, so it is
# recomputed at most every 5 minutes rather than on every 15-second scrape
MODEL_TTL_SECONDS = 5 * 60

# The newest row of each source. Observed weather can include hours ahead, so only the past counts.
FRESHNESS_SQL = text("""
    SELECT 'purpleair' AS source, max(time) AS newest FROM lowcost_readings
    UNION ALL SELECT 'airnow', max(time) FROM reference_readings
    UNION ALL SELECT 'weather', max(time) FROM weather WHERE time <= now()
    UNION ALL SELECT 'day_ahead_weather', max(time) FROM day_ahead_weather
    UNION ALL SELECT 'corrected', max(time) FROM corrected_readings
    UNION ALL SELECT 'forecast', max(issue_time) FROM forecasts
""")

# For each job: when it last started and last succeeded, and how its latest finished run went
JOBS_SQL = text("""
    WITH latest AS (
        SELECT DISTINCT ON (task)
            task,
            status,
            extract(epoch FROM finished_at - started_at) AS duration,
            rows_upserted
        FROM ingestion_runs
        WHERE status <> 'running'
        ORDER BY task, started_at DESC
    )
    SELECT
        r.task,
        max(r.started_at) AS last_start,
        max(r.finished_at) FILTER (WHERE r.status = 'succeeded') AS last_success,
        l.status AS last_status,
        l.duration AS last_duration,
        l.rows_upserted AS last_rows
    FROM ingestion_runs r
    LEFT JOIN latest l ON l.task = r.task
    GROUP BY r.task, l.status, l.duration, l.rows_upserted
""")

MONITORS_ON_RAW_SQL = text(
    "SELECT count(DISTINCT station_id) FROM serving_sources WHERE source = 'raw'"
)


def gauge(name: str, documentation: str, labels: list[str] | None = None) -> GaugeMetricFamily:
    return GaugeMetricFamily(name, documentation, labels=labels)


def seconds(moment: datetime | None) -> float | None:
    return None if moment is None else moment.timestamp()


@dataclass
class ModelCache:
    """The last model metrics and when they were computed."""

    metrics: list[Metric] = field(default_factory=list)
    computed_at: float = float("-inf")
    complete: bool = True  # False when MLflow couldn't be read and the champion's MAE is missing


class PipelineCollector(Collector):
    """Answers each scrape with fresh queries; the slower model metrics are cached."""

    def __init__(
        self,
        engine: Engine,
        redis_client: "redis.Redis | None",
        champion: Callable[[], ModelInfo | None] = load_champion_info,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.engine, self.redis, self.champion = engine, redis_client, champion
        self.clock, self.monotonic = clock, monotonic
        self.model = ModelCache()
        self.lock = threading.Lock()  # scrapes can overlap

    def collect(self) -> Iterator[Metric]:
        started = self.monotonic()
        up = 1.0
        try:
            yield from self.freshness()
            yield from self.jobs()
        except Exception:
            logger.exception("Pipeline metrics failed")
            up = 0.0
        try:
            yield from self.queue()
        except Exception:
            logger.exception("Queue length failed")
            up = 0.0
        with self.lock:
            if self.monotonic() - self.model.computed_at >= MODEL_TTL_SECONDS:
                try:
                    self.model = self.compute_model_metrics()
                except Exception:
                    # Keep serving the last good numbers; try again on the next scrape
                    logger.exception("Model metrics failed")
                    up = 0.0
            if not self.model.complete:
                up = 0.0
            yield from self.model.metrics
        status = gauge("airsight_exporter_up", "1 if every query of the last scrape worked")
        status.add_metric([], up)
        yield status
        duration = gauge("airsight_exporter_scrape_duration_seconds", "Time the last scrape took")
        duration.add_metric([], self.monotonic() - started)
        yield duration

    def freshness(self) -> Iterator[Metric]:
        newest = gauge(
            "airsight_data_newest_timestamp_seconds",
            "Time of the newest stored row of each source (Unix seconds); age = time() - this",
            ["source"],
        )
        with self.engine.connect() as connection:
            for row in connection.execute(FRESHNESS_SQL):
                if (value := seconds(row.newest)) is not None:
                    newest.add_metric([row.source], value)
        yield newest

    def jobs(self) -> Iterator[Metric]:
        start = gauge(
            "airsight_job_last_start_timestamp_seconds", "When each job last started", ["task"]
        )
        success = gauge(
            "airsight_job_last_success_timestamp_seconds",
            "When each job last finished successfully",
            ["task"],
        )
        failed = gauge(
            "airsight_job_last_failed", "1 if the job's latest finished run failed", ["task"]
        )
        duration = gauge(
            "airsight_job_last_duration_seconds", "How long the latest finished run took", ["task"]
        )
        rows = gauge("airsight_job_last_rows", "Rows the latest finished run wrote", ["task"])
        with self.engine.connect() as connection:
            for row in connection.execute(JOBS_SQL):
                if (value := seconds(row.last_start)) is not None:
                    start.add_metric([row.task], value)
                if (value := seconds(row.last_success)) is not None:
                    success.add_metric([row.task], value)
                if row.last_status is not None:
                    failed.add_metric([row.task], float(row.last_status == "failed"))
                if row.last_duration is not None:
                    duration.add_metric([row.task], float(row.last_duration))
                if row.last_rows is not None:
                    rows.add_metric([row.task], float(row.last_rows))
        yield from (start, success, failed, duration, rows)

    def queue(self) -> Iterator[Metric]:
        if self.redis is None:
            return
        waiting = gauge("airsight_queue_length", "Tasks waiting in the Celery queue")
        waiting.add_metric([], float(self.redis.llen(QUEUE)))
        yield waiting

    def compute_model_metrics(self) -> ModelCache:
        try:
            champion = self.champion()
            complete = True
        except Exception:
            # MLflow is down: the rest still comes from the database
            logger.exception("Could not read the champion from MLflow")
            champion, complete = None, False
        return ModelCache(list(self.model_metrics(champion)), self.monotonic(), complete)

    def model_metrics(self, champion: ModelInfo | None) -> Iterator[Metric]:
        end = self.clock().replace(minute=0, second=0, microsecond=0)
        with self.engine.connect() as connection:
            on_raw = gauge(
                "airsight_model_monitors_on_raw",
                "Official monitors whose nearby sensors show the raw reading (ADR 0010)",
            )
            on_raw.add_metric([], float(connection.execute(MONITORS_ON_RAW_SQL).scalar_one()))
            yield on_raw

            if champion is not None:
                # The same window as the accuracy page: only hours the champion never saw
                start = end - timedelta(days=CORRECTION_DAYS)
                if champion.trained_before is not None:
                    start = min(max(start, champion.trained_before), end)
                scores = accuracy.score(connection, champion.model_version, start, end)
                mae = gauge(
                    "airsight_model_live_mae",
                    f"Live {CORRECTION_DAYS}-day MAE against the official monitors, µg/m³",
                    ["model"],
                )
                for model, value in scores.headline_mae.model_dump().items():
                    if value is not None:
                        mae.add_metric([model], value)
                hours = gauge("airsight_model_scored_hours", "Hours behind airsight_model_live_mae")
                hours.add_metric([], float(scores.hours))
                yield from (mae, hours)

            forecast = forecast_accuracy.score(connection, end - timedelta(days=FORECAST_DAYS), end)
            forecast_mae = gauge(
                "airsight_forecast_live_mae",
                f"Live {FORECAST_DAYS}-day MAE of the forecast and its two baselines, µg/m³",
                ["model"],
            )
            for model, value in forecast.headline_mae.model_dump().items():
                if value is not None:
                    forecast_mae.add_metric([model], value)
            forecast_hours = gauge(
                "airsight_forecast_scored_hours", "Forecast hours scored in the window"
            )
            forecast_hours.add_metric([], float(forecast.hours))
            yield from (forecast_mae, forecast_hours)
            if forecast.coverage is not None:
                coverage = gauge(
                    "airsight_forecast_coverage",
                    "Share of scored hours inside the forecast's p10 to p90 range; 0.8 is the aim",
                )
                coverage.add_metric([], forecast.coverage)
                yield coverage


def main() -> None:
    # MLflow retries a failed request for minutes by default; a scrape must not wait that long.
    # If MLflow is down, the champion's accuracy is skipped for this round and retried later.
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
    configure_logging()
    settings = get_settings()
    registry = CollectorRegistry()
    registry.register(PipelineCollector(get_engine(), redis.Redis.from_url(settings.redis_url)))
    start_http_server(PORT, registry=registry)
    logger.info("Exporter serving metrics on port %d", PORT)
    threading.Event().wait()  # the server runs in its own thread; keep the process alive


if __name__ == "__main__":
    main()
