from datetime import UTC, datetime

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import Engine, create_engine, text

from airsight.api.schemas import ModelInfo
from airsight.observability import exporter
from airsight.observability.exporter import MODEL_TTL_SECONDS, PipelineCollector
from airsight.worker import runs

NOW = datetime(2026, 11, 17, 6, 30, tzinfo=UTC)
CHAMPION = ModelInfo(
    name="airsight-correction",
    version=99,
    model_version="airsight-correction/99",  # no corrections stored for it: nothing to score
    dataset=None,
    trained_before=None,
    promoted_at=NOW,
    final_test=None,
    model_card="https://example.com/card",
)

Samples = dict[tuple[str, frozenset[tuple[str, str]]], float]


class FakeRedis:
    def __init__(self, waiting: int) -> None:
        self.waiting = waiting

    def llen(self, name: str) -> int:
        assert name == "celery"
        return self.waiting


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def scrape(collector: PipelineCollector) -> Samples:
    registry = CollectorRegistry()
    registry.register(collector)
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in text_string_to_metric_families(generate_latest(registry).decode())
        for sample in family.samples
    }


def value(samples: Samples, name: str, **labels: str) -> float | None:
    return samples.get((name, frozenset(labels.items())))


def collector(engine: Engine, **overrides: object) -> PipelineCollector:
    options: dict[str, object] = {
        "redis_client": FakeRedis(3),
        "champion": lambda: CHAMPION,
        "clock": lambda: NOW,
        "monotonic": Clock(),
    }
    options.update(overrides)
    return PipelineCollector(engine, **options)  # type: ignore[arg-type]


def test_freshness_is_the_newest_row_of_each_source(engine: Engine) -> None:
    with engine.begin() as connection:
        newest = connection.execute(text("SELECT max(time) FROM reference_readings")).scalar()

    samples = scrape(collector(engine))

    assert value(samples, "airsight_exporter_up") == 1.0
    if newest is not None:  # other test modules may or may not have stored AirNow rows yet
        stored = value(samples, "airsight_data_newest_timestamp_seconds", source="airnow")
        assert stored == newest.timestamp()


def test_each_job_reports_its_last_start_success_and_outcome(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO ingestion_runs (task, started_at, finished_at, status, rows_upserted)
                VALUES
                    ('exporter_test', '2026-11-17 03:00+00', '2026-11-17 03:01+00',
                     'succeeded', 120),
                    ('exporter_test', '2026-11-17 06:00+00', '2026-11-17 06:00:30+00',
                     'failed', 0),
                    ('exporter_test', '2026-11-17 06:20+00', NULL, 'running', NULL)
            """)
        )

    samples = scrape(collector(engine))

    task = {"task": "exporter_test"}
    started = datetime(2026, 11, 17, 6, 20, tzinfo=UTC).timestamp()
    succeeded = datetime(2026, 11, 17, 3, 1, tzinfo=UTC).timestamp()
    assert value(samples, "airsight_job_last_start_timestamp_seconds", **task) == started
    assert value(samples, "airsight_job_last_success_timestamp_seconds", **task) == succeeded
    # The running one hasn't finished, so "latest finished" is the failure at 06:00
    assert value(samples, "airsight_job_last_failed", **task) == 1.0
    assert value(samples, "airsight_job_last_duration_seconds", **task) == 30.0
    assert value(samples, "airsight_job_last_rows", **task) == 0.0


def test_queue_length_and_model_metrics(engine: Engine) -> None:
    samples = scrape(collector(engine))

    assert value(samples, "airsight_queue_length") == 3.0
    assert value(samples, "airsight_model_monitors_on_raw") is not None
    assert value(samples, "airsight_model_scored_hours") == 0.0  # nothing stored for v99
    assert value(samples, "airsight_forecast_scored_hours") is not None


def test_model_metrics_are_recomputed_at_most_every_five_minutes(engine: Engine) -> None:
    calls = []
    clock = Clock()

    def champion() -> ModelInfo:
        calls.append(clock.now)
        return CHAMPION

    pipeline = collector(engine, champion=champion, monotonic=clock)

    scrape(pipeline)
    clock.now = MODEL_TTL_SECONDS - 1
    samples = scrape(pipeline)
    clock.now = MODEL_TTL_SECONDS
    scrape(pipeline)

    assert calls == [0.0, MODEL_TTL_SECONDS]
    assert value(samples, "airsight_model_scored_hours") == 0.0  # served from the cache


def test_no_champion_still_reports_the_rest(engine: Engine) -> None:
    samples = scrape(collector(engine, champion=lambda: None))

    assert value(samples, "airsight_model_scored_hours") is None
    assert value(samples, "airsight_exporter_up") == 1.0


def test_mlflow_down_still_reports_what_the_database_knows(engine: Engine) -> None:
    def champion() -> ModelInfo:
        raise ConnectionError("MLflow is down")

    samples = scrape(collector(engine, champion=champion))

    assert value(samples, "airsight_exporter_up") == 0.0
    assert value(samples, "airsight_model_scored_hours") is None
    assert value(samples, "airsight_model_monitors_on_raw") is not None
    assert value(samples, "airsight_forecast_scored_hours") is not None


def test_an_unreachable_database_says_so_instead_of_failing() -> None:
    broken = create_engine("postgresql+psycopg://airsight:airsight@127.0.0.1:1/airsight")

    samples = scrape(collector(broken))

    assert value(samples, "airsight_exporter_up") == 0.0
    assert value(samples, "airsight_queue_length") == 3.0  # Redis still answered


def test_every_task_but_the_self_recorded_ones_records_its_run(engine: Engine) -> None:
    runs.record_start(engine, "task-1", "airsight.correct_readings")
    runs.record_finish(engine, "task-1", "SUCCESS", 8)
    runs.record_start(engine, "task-2", "airsight.issue_forecast")
    runs.record_finish(engine, "task-2", "FAILURE", RuntimeError("no weather"))
    runs.record_start(engine, "task-3", "airsight.ingest_live")  # records itself as "live"
    runs.record_finish(engine, "task-3", "SUCCESS", {"reference_rows": 5})
    runs.record_start(engine, "task-4", "airsight.check_quality")  # records itself as "quality"
    runs.record_finish(engine, "task-4", "SUCCESS", 8)

    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT DISTINCT ON (task) task, status, rows_upserted, error, finished_at
                FROM ingestion_runs
                WHERE task IN ('correct_readings', 'issue_forecast', 'ingest_live', 'check_quality')
                ORDER BY task, id DESC
            """)
        ).all()
    found = {row.task: row for row in rows}
    assert set(found) == {"correct_readings", "issue_forecast"}
    assert (found["correct_readings"].status, found["correct_readings"].rows_upserted) == (
        "succeeded",
        8,
    )
    assert (found["issue_forecast"].status, found["issue_forecast"].error) == (
        "failed",
        "RuntimeError",
    )
    assert all(row.finished_at is not None for row in rows)


@pytest.mark.parametrize(
    ("result", "rows"),
    [
        (24, 24),
        ({"reference_rows": 60, "lowcost_rows": 40, "points_spent": 242, "skipped": False}, 100),
        (True, 0),
        (None, 0),
    ],
)
def test_rows_come_from_what_the_task_returns(result: object, rows: int) -> None:
    assert runs.rows_from(result) == rows


def test_a_recording_failure_never_breaks_the_job() -> None:
    broken = create_engine("postgresql+psycopg://airsight:airsight@127.0.0.1:1/airsight")

    runs.record_start(broken, "task-x", "airsight.correct_readings")  # logs a warning, no raise
    runs.record_finish(broken, "task-x", "SUCCESS", 1)


def test_the_exporter_listens_on_its_port() -> None:
    assert exporter.PORT == 9108
