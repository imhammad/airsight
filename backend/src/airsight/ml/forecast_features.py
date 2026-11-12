"""Forecast rows: one per sensor, issue hour and hour ahead (ADR 0012).

Training and serving both build their rows here, so a forecast input can never be computed one
way for the model's lessons and another way for its answers. Every input is known at the issue
hour; only the label (the official reading at the target hour) comes from the future.
"""

from datetime import datetime

import pandas as pd

from airsight.ml.features import LOCAL_TIMEZONE

HORIZONS = range(1, 25)  # hours ahead
# The live job runs at :15 past 00, 03, 06 ... UTC, when the newest complete hour is 23, 02,
# 05 ... So training issues forecasts at those same hours, every 3 hours.
ISSUE_EVERY_HOURS = 3
ISSUE_HOUR_OFFSET = 2
# A monitor reading older than this isn't "now" any more
OFFICIAL_MAX_AGE_HOURS = 3

WEATHER_COLUMNS = [
    "temperature",
    "relative_humidity",
    "wind_speed",
    "wind_direction",
    "precipitation",
]
FORECAST_FEATURES = [
    "raw_now",
    "raw_mean_3h",
    "raw_mean_24h",
    "raw_day_before",  # the sensor 24 hours before the target hour
    "official_now",
    "horizon",
    "local_hour",  # of the target hour
    "day_of_week",
    *WEATHER_COLUMNS,  # forecast for the target hour
]
TARGET = "official"


def _one_sensor(hours: pd.DataFrame, official: pd.Series, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forecast rows of one sensor: its issue hours times every horizon."""
    raw = hours.set_index("time")["raw"].reindex(index)
    official = official.reindex(index)
    now = pd.DataFrame(
        {
            "raw_now": raw,
            "raw_mean_3h": raw.rolling(3, min_periods=1).mean(),
            "raw_mean_24h": raw.rolling(24, min_periods=12).mean(),
            "official_now": official.ffill(limit=OFFICIAL_MAX_AGE_HOURS - 1),
        },
        index=index,
    )
    on_schedule = (index.hour % ISSUE_EVERY_HOURS) == ISSUE_HOUR_OFFSET
    issues = now[raw.notna().to_numpy() & on_schedule]
    parts = []
    for horizon in HORIZONS:
        part = issues.copy()
        part["horizon"] = horizon
        # shift(k) looks k hours back, shift(-k) k hours ahead, from each issue hour
        part["raw_day_before"] = raw.shift(24 - horizon).reindex(issues.index)
        part["official_day_before"] = official.shift(24 - horizon).reindex(issues.index)
        part[TARGET] = official.shift(-horizon).reindex(issues.index)
        parts.append(part)
    rows = pd.concat(parts).rename_axis("issue_time").reset_index()
    rows["target_time"] = rows["issue_time"] + pd.to_timedelta(rows["horizon"], unit="h")
    first = hours.iloc[0]
    for column in ("sensor_id", "station_id", "station", "cell_id"):
        rows[column] = first[column]
    return rows


def forecast_rows(
    sensor_hours: pd.DataFrame,
    official: pd.DataFrame,
    weather: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Rows for every scheduled issue hour in [start, end), with features and the label.

    sensor_hours: sensor_id, station_id, station, cell_id, time, raw (NaN for flagged hours)
    official: station_id, time, official
    weather: cell_id, time and WEATHER_COLUMNS, as forecast before each hour

    The label is NaN where the monitor has no reading for the target hour, such as every
    target after `end`; training drops those rows, serving has no label at all.
    """
    index = pd.date_range(start, end, freq="h", inclusive="left", name="time")
    by_station = {
        station: rows.set_index("time")["official"]
        for station, rows in official.groupby("station_id")
    }
    empty = pd.Series(dtype=float)
    parts = [
        _one_sensor(hours, by_station.get(hours["station_id"].iloc[0], empty), index)
        for _, hours in sensor_hours.groupby("sensor_id", sort=True)
    ]
    if not parts:
        return pd.DataFrame(columns=[*FORECAST_FEATURES, TARGET, "issue_time", "target_time"])
    rows = pd.concat(parts, ignore_index=True)
    rows = rows.merge(
        weather.rename(columns={"time": "target_time"}),
        on=["cell_id", "target_time"],
        how="left",
    )
    local = rows["target_time"].dt.tz_convert(LOCAL_TIMEZONE)
    rows["local_hour"] = local.dt.hour
    rows["day_of_week"] = local.dt.day_of_week
    return rows.sort_values(["sensor_id", "issue_time", "horizon"]).reset_index(drop=True)
