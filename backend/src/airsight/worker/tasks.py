"""Tasks the worker runs. Each one is a thin wrapper around tested ingestion code."""

from dataclasses import asdict

from airsight.ingestion import live
from airsight.worker.celery_app import app


@app.task(name="airsight.ingest_live")
def ingest_live() -> dict[str, int | bool]:
    """Fetch what's new from AirNow, PurpleAir and Open-Meteo (every 3 hours, ADR 0006)."""
    return asdict(live.run_with_real_clients())
