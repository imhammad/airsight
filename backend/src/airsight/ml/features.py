"""Model features, computed the same way for training and for serving.

Every feature the model sees is derived here from the columns the database stores, so the
training data and the live predictions can never compute a feature differently.
"""

import pandas as pd

# Local time matters more than UTC: traffic and wood smoke follow the day in California
LOCAL_TIMEZONE = "America/Los_Angeles"

# What the database must provide for each sensor-hour
INPUT_COLUMNS = [
    "time",
    "pm25_a",
    "pm25_b",
    "humidity",
    "temperature",
    "relative_humidity",
    "wind_speed",
    "precipitation",
]

# No sensor_humidity since #100: two sensors don't report it, and leaving it out cost 0.01 µg/m³
# of headline MAE. Outdoor humidity from Open-Meteo stays, for every sensor.
FEATURE_COLUMNS = [
    "raw",
    "channel_difference",
    "temperature",
    "relative_humidity",
    "wind_speed",
    "precipitation",
    "local_hour",
    "day_of_week",
]


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of frame with every column in FEATURE_COLUMNS added."""
    missing = set(INPUT_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"missing input columns: {sorted(missing)}")
    out = frame.copy()
    out["raw"] = (out["pm25_a"] + out["pm25_b"]) / 2
    out["channel_difference"] = (out["pm25_a"] - out["pm25_b"]).abs()
    out["sensor_humidity"] = out["humidity"]  # not a model feature; the EPA baseline uses it
    local = pd.to_datetime(out["time"], utc=True).dt.tz_convert(LOCAL_TIMEZONE)
    out["local_hour"] = local.dt.hour
    out["day_of_week"] = local.dt.day_of_week
    return out
