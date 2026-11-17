"""Every scheduled task leaves a row in ingestion_runs (ADR 0013).

The exporter reads these rows to tell when each job last ran, how long it took and whether it
worked. Because the evidence is in the database, a worker that has stopped cannot look healthy.
The table keeps its first name; it now holds every job, not only ingestion.
"""

import logging
from typing import Any

from sqlalchemy import Engine

from airsight.ingestion import store

logger = logging.getLogger(__name__)

# Live ingestion records its own run as "live", inside its database lock, so a run skipped
# because another holds the lock isn't counted (ingestion/live.py)
SELF_RECORDED = {"airsight.ingest_live"}

# Runs started in this worker process and not finished yet, by Celery task ID
_open_runs: dict[str, int] = {}


def run_name(task_name: str) -> str:
    """airsight.issue_forecast is recorded as issue_forecast, next to live ingestion's "live"."""
    return task_name.removeprefix("airsight.")


def rows_from(result: Any) -> int:
    """Rows a task wrote: its return value when that is a count, or the *_rows fields it reports."""
    if isinstance(result, bool):
        return 0
    if isinstance(result, int):
        return result
    if isinstance(result, dict):
        return sum(v for k, v in result.items() if k.endswith("_rows") and isinstance(v, int))
    return 0


def record_start(engine: Engine, task_id: str, task_name: str) -> None:
    if task_name in SELF_RECORDED:
        return
    try:
        with engine.begin() as connection:
            _open_runs[task_id] = store.start_run(connection, run_name(task_name))
    except Exception:
        # Recording is for monitoring; it must never stop the job itself
        logger.warning("Could not record the start of %s", task_name, exc_info=True)


def record_finish(engine: Engine, task_id: str, state: str | None, result: Any) -> None:
    run_id = _open_runs.pop(task_id, None)
    if run_id is None:
        return
    succeeded = state == "SUCCESS"
    try:
        with engine.begin() as connection:
            store.finish_run(
                connection,
                run_id,
                "succeeded" if succeeded else "failed",
                rows_from(result) if succeeded else 0,
                None if succeeded else type(result).__name__,
            )
    except Exception:
        logger.warning("Could not record the end of run %d", run_id, exc_info=True)
