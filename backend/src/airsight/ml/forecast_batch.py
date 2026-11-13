"""Issue the 24-hour air quality forecast with the champion model and store it (ADR 0012).

The worker runs this every 3 hours at :45, after live ingestion and the correction. It issues
from the newest complete hour on the training schedule (02, 05 ... 23 UTC), with the latest
weather forecast from Open-Meteo, and stores all 24 hours. Every issue is kept; issuing the same
hour again replaces it. The API only ever reads the stored forecasts.

Issue once by hand, from backend/ with the stack up:  uv run python -m airsight.ml.forecast_batch
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import mlflow
import numpy as np
import pandas as pd
from sqlalchemy import Engine, func, text
from sqlalchemy.dialects.postgresql import insert

from airsight.core.config import get_settings
from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.core.tables import forecasts
from airsight.ingestion.http_client import create_client
from airsight.ingestion.open_meteo import OpenMeteoClient, Point, WeatherHour
from airsight.ml.forecast_dataset import OFFICIAL_SQL, SENSOR_HOURS_SQL
from airsight.ml.forecast_features import (
    ISSUE_EVERY_HOURS,
    ISSUE_HOUR_OFFSET,
    WEATHER_COLUMNS,
    forecast_rows,
)
from airsight.ml.forecast_registry import load_champion_version
from airsight.ml.forecast_train import bundle_input

logger = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
HISTORY = timedelta(hours=24)  # raw_mean_24h needs the day before the issue hour
# ADR 0012: above this, the air is outside what the model learned from
UNSEEN_AIR = 35.4
WEATHER_DAYS = 3  # today and the next two days cover every target hour

EXCLUDED_SQL = text("SELECT sensor_id FROM sensor_health WHERE status = 'excluded'")


class StoredForecastModel(Protocol):
    """The champion as MLflow loads it: p10, p50 and p90 for rows of forecast features."""

    def predict(self, data: pd.DataFrame) -> Any: ...


class UpcomingWeatherSource(Protocol):
    def upcoming(
        self, points: Sequence[Point], days: int = ...
    ) -> dict[Point, list[WeatherHour]]: ...


def latest_issue_time(now: datetime) -> datetime:
    """The newest complete hour on the issue schedule: at 03:45 UTC, 02:00 UTC."""
    hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0) - HOUR
    while hour.hour % ISSUE_EVERY_HOURS != ISSUE_HOUR_OFFSET:
        hour -= HOUR
    return hour


def mark_unseen_air(rows: pd.DataFrame, predicted: pd.DataFrame) -> pd.DataFrame:
    """ADR 0012: above 35.4 µg/m³, now or forecast, mark it and widen to 0.5 to 1.5 times p50."""
    outside = (rows["official_now"].fillna(0.0) > UNSEEN_AIR) | (predicted["p50"] > UNSEEN_AIR)
    marked = predicted.copy()
    marked["p10"] = np.where(outside, np.minimum(marked["p10"], 0.5 * marked["p50"]), marked["p10"])
    marked["p90"] = np.where(outside, np.maximum(marked["p90"], 1.5 * marked["p50"]), marked["p90"])
    marked["outside_experience"] = outside.to_numpy()
    return marked


def _weather_frame(source: UpcomingWeatherSource, cells: Sequence[str]) -> pd.DataFrame:
    points = {Point(*map(float, cell.split(","))): cell for cell in cells}
    answer = source.upcoming(list(points), WEATHER_DAYS)
    records = [
        {
            "cell_id": points[point],
            "time": hour.time,
            "temperature": hour.temperature,
            "relative_humidity": hour.relative_humidity,
            "wind_speed": hour.wind_speed,
            "wind_direction": hour.wind_direction,
            "precipitation": hour.precipitation,
        }
        for point, hours in answer.items()
        for hour in hours
    ]
    weather = pd.DataFrame(records, columns=["cell_id", "time", *WEATHER_COLUMNS])
    weather["time"] = pd.to_datetime(weather["time"], utc=True)
    return weather


def issue_forecast(
    engine: Engine,
    model: StoredForecastModel,
    model_version: str,
    weather_source: UpcomingWeatherSource,
    issue_time: datetime,
) -> int:
    """Forecast the next 24 hours from issue_time for every healthy paired sensor, and store it.

    A sensor with no clean reading at the issue hour gets no forecast, as in training. Returns
    the number of hours stored.
    """
    params = {"start": issue_time - HISTORY, "end": issue_time + HOUR}
    with engine.connect() as connection:
        excluded = set(connection.execute(EXCLUDED_SQL).scalars())
        sensor_hours = pd.read_sql(SENSOR_HOURS_SQL, connection, params=params)
        official = pd.read_sql(OFFICIAL_SQL, connection, params=params)
    sensor_hours = sensor_hours[~sensor_hours["sensor_id"].isin(excluded)]
    if sensor_hours.empty:
        return 0
    weather = _weather_frame(weather_source, sorted(sensor_hours["cell_id"].unique()))
    rows = forecast_rows(sensor_hours, official, weather, params["start"], params["end"])
    rows = rows[rows["issue_time"] == pd.Timestamp(issue_time)].reset_index(drop=True)
    if rows.empty:
        return 0

    predicted = pd.DataFrame(model.predict(bundle_input(rows)))[["p10", "p50", "p90"]]
    predicted.index = rows.index
    predicted = mark_unseen_air(rows, predicted.clip(lower=0.0))  # PM2.5 is never below 0
    keys = rows[["sensor_id", "issue_time", "horizon", "target_time"]]
    records = [
        {
            "sensor_id": int(r["sensor_id"]),
            "issue_time": r["issue_time"].to_pydatetime(),
            "horizon": int(r["horizon"]),
            "target_time": r["target_time"].to_pydatetime(),
            "p10": float(r["p10"]),
            "p50": float(r["p50"]),
            "p90": float(r["p90"]),
            "outside_experience": bool(r["outside_experience"]),
            "model_version": model_version,
        }
        for r in pd.concat([keys, predicted], axis=1).to_dict("records")
    ]
    statement = insert(forecasts).values(records)
    with engine.begin() as connection:
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=["sensor_id", "issue_time", "horizon"],
                set_={
                    **{c: statement.excluded[c] for c in ("target_time", "p10", "p50", "p90")},
                    "outside_experience": statement.excluded.outside_experience,
                    "model_version": statement.excluded.model_version,
                    "computed_at": func.now(),
                },
            )
        )
    return len(records)


def forecast_latest(engine: Engine, now: datetime | None = None) -> int:
    """Issue from the newest scheduled hour with the champion and live weather. The worker's job."""
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    model, model_version = load_champion_version()
    issue_time = latest_issue_time(now or datetime.now(UTC))
    with create_client(get_settings().http_timeout_seconds) as http:
        count = issue_forecast(engine, model, model_version, OpenMeteoClient(http), issue_time)
    logger.info("Forecast %d hours issued at %s with %s", count, issue_time, model_version)
    return count


def main() -> None:
    configure_logging()
    forecast_latest(get_engine())


if __name__ == "__main__":
    main()
