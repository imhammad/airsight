"""Forecast rows: every input known at the issue hour, the label from the target hour."""

import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from airsight.ml.forecast_features import FORECAST_FEATURES, HORIZONS, forecast_rows

START = datetime(2026, 3, 1, tzinfo=UTC)
DAYS = 3
END = START + timedelta(days=DAYS)


def hour(n: int) -> pd.Timestamp:
    return pd.Timestamp(START + timedelta(hours=n))


def inputs(
    flagged: frozenset[int] = frozenset(), no_official: frozenset[int] = frozenset()
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Values that tell the hours apart: raw is the hour number, official is 100 plus it,
    and the forecast temperature is 200 plus it."""
    hours = range(DAYS * 24)
    sensor_hours = pd.DataFrame(
        {
            "sensor_id": 1,
            "station_id": 10,
            "station": "A",
            "cell_id": "36.6,-121.9",
            "time": [hour(h) for h in hours],
            "raw": [math.nan if h in flagged else float(h) for h in hours],
        }
    )
    official = pd.DataFrame(
        {
            "station_id": 10,
            "time": [hour(h) for h in hours if h not in no_official],
            "official": [100.0 + h for h in hours if h not in no_official],
        }
    )
    weather = pd.DataFrame(
        {
            "cell_id": "36.6,-121.9",
            "time": [hour(h) for h in range(DAYS * 24 + 24)],
            "temperature": [200.0 + h for h in range(DAYS * 24 + 24)],
            "relative_humidity": 70.0,
            "wind_speed": 5.0,
            "wind_direction": 270.0,
            "precipitation": 0.0,
        }
    )
    return sensor_hours, official, weather


def test_forecasts_are_issued_every_three_hours_for_24_hours_ahead() -> None:
    rows = forecast_rows(*inputs(), START, END)

    issues = sorted(set(rows["issue_time"]))
    assert issues[:3] == [hour(2), hour(5), hour(8)]  # 02:00, 05:00, 08:00 UTC ...
    assert len(issues) == DAYS * 8
    assert rows.groupby("issue_time")["horizon"].apply(list).iloc[0] == list(HORIZONS)
    assert set(FORECAST_FEATURES) <= set(rows.columns)


def test_inputs_come_from_the_issue_hour_and_the_label_from_the_target() -> None:
    rows = forecast_rows(*inputs(), START, END)

    row = rows[(rows["issue_time"] == hour(26)) & (rows["horizon"] == 5)].iloc[0]
    assert row["raw_now"] == 26
    assert row["raw_mean_3h"] == 25  # hours 24, 25 and 26
    assert row["raw_mean_24h"] == pytest.approx(sum(range(3, 27)) / 24)
    assert row["raw_day_before"] == 31 - 24  # the target is hour 31
    assert row["official_now"] == 126
    assert row["official_day_before"] == 107
    assert row["temperature"] == 231  # forecast weather for the target hour
    assert row["official"] == 131  # the label
    assert row["target_time"] == hour(31)


def test_no_input_ever_comes_from_after_the_issue_hour() -> None:
    rows = forecast_rows(*inputs(), START, END)
    issue_hour = (rows["issue_time"] - pd.Timestamp(START)).dt.total_seconds() / 3600

    for column in ("raw_now", "raw_mean_3h", "raw_mean_24h", "raw_day_before"):
        known = rows[column].notna()  # early hours have no 24-hour history yet
        assert (rows.loc[known, column] <= issue_hour[known]).all(), column
    assert (rows["official_now"] - 100 <= issue_hour).all()


def test_no_forecast_is_issued_from_a_flagged_hour() -> None:
    rows = forecast_rows(*inputs(flagged=frozenset({5})), START, END)

    assert hour(5) not in set(rows["issue_time"])
    assert hour(8) in set(rows["issue_time"])


def test_a_late_monitor_reading_is_used_for_two_hours_only() -> None:
    rows = forecast_rows(*inputs(no_official=frozenset({4, 5, 7, 8, 9, 10, 11})), START, END)
    first = rows[rows["horizon"] == 1].set_index("issue_time")["official_now"]

    assert first[hour(5)] == 103  # hour 3's reading, two hours old
    assert math.isnan(first[hour(11)])  # hour 6's would be five hours old


def test_targets_after_the_end_have_no_label() -> None:
    rows = forecast_rows(*inputs(), START, END)

    last_issue = rows[rows["issue_time"] == rows["issue_time"].max()]
    assert last_issue["official"].isna().all()  # every target is after END


def test_target_hours_use_california_time() -> None:
    rows = forecast_rows(*inputs(), START, END)

    row = rows[(rows["issue_time"] == hour(2)) & (rows["horizon"] == 1)].iloc[0]
    assert row["local_hour"] == 19  # 03:00 UTC on 1 March is 19:00 the day before in PST
    assert row["day_of_week"] == 5  # Saturday


def test_start_and_end_may_use_different_utc_timezone_objects() -> None:
    # The database returns "Etc/UTC"; datetime.UTC is "UTC" (the bug the first real run hit)
    start = START.astimezone(ZoneInfo("Etc/UTC"))

    rows = forecast_rows(*inputs(), start, END)

    assert len(set(rows["issue_time"])) == DAYS * 8
