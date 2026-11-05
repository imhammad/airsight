"""Tasks the worker runs. Each one is a thin wrapper around tested ingestion code."""

from dataclasses import asdict

from airsight.core.db import get_engine
from airsight.ingestion import live, quality
from airsight.worker.celery_app import app


@app.task(name="airsight.ingest_live")
def ingest_live() -> dict[str, int | bool]:
    """Fetch what's new from AirNow, PurpleAir and Open-Meteo (every 3 hours, ADR 0006)."""
    return asdict(live.run_with_real_clients())


@app.task(name="airsight.check_quality")
def check_quality() -> int:
    """Recompute which sensors are healthy enough to use (daily)."""
    return len(quality.run_quality_check(get_engine()))
