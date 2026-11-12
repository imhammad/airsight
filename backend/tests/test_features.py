"""Golden values for the feature code.

A model learns from features computed one exact way. If someone changes that math, every model
already trained becomes silently wrong, so any change to these numbers must be deliberate:
update this test, retrain, and promote again.
"""

import math

import pandas as pd

from airsight.ml.features import FEATURE_COLUMNS, add_features

# Three hours around the end of daylight saving time in California (1 Nov 2026, 02:00 PDT)
ROWS = pd.DataFrame(
    {
        "time": pd.to_datetime(
            ["2026-11-01T08:00Z", "2026-11-01T09:00Z", "2026-11-01T10:00Z"], utc=True
        ),
        "pm25_a": [10.0, 3.0, 0.0],
        "pm25_b": [12.0, 9.0, 0.0],
        "humidity": [55.0, 80.0, 40.0],
        "temperature": [12.5, 11.0, None],  # weather can be missing
        "relative_humidity": [70.0, 85.0, 60.0],
        "wind_speed": [3.0, 0.0, 7.5],
        "precipitation": [0.0, 0.2, 0.0],
    }
)

GOLDEN = {
    "raw": [11.0, 6.0, 0.0],
    "channel_difference": [2.0, 6.0, 0.0],
    "temperature": [12.5, 11.0, math.nan],
    "relative_humidity": [70.0, 85.0, 60.0],
    "wind_speed": [3.0, 0.0, 7.5],
    "precipitation": [0.0, 0.2, 0.0],
    "local_hour": [1, 1, 2],  # 01:00 PDT, then 01:00 PST again, then 02:00 PST
    "day_of_week": [6, 6, 6],  # Sunday
}


def test_feature_values_are_unchanged() -> None:
    features = add_features(ROWS)

    assert list(GOLDEN) == FEATURE_COLUMNS  # same features, same order
    pd.testing.assert_frame_equal(
        features[FEATURE_COLUMNS].reset_index(drop=True),
        pd.DataFrame(GOLDEN),
        check_dtype=False,
    )
    # Not a model feature since #100, but the EPA baseline still reads it
    assert features["sensor_humidity"].tolist() == [55.0, 80.0, 40.0]


def test_input_rows_are_not_modified() -> None:
    before = ROWS.copy()

    add_features(ROWS)

    pd.testing.assert_frame_equal(ROWS, before)
