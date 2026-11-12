from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from airsight.ml.forecast_evaluation import (
    FOLDS,
    ForecastReport,
    Persistence,
    SameHourYesterday,
    backtest,
    fold_starts,
    pinball_loss,
    score,
    ship_check,
    split_final_test,
)

START = datetime(2026, 5, 1, tzinfo=UTC)
FINAL_TEST_START = START + timedelta(days=35)


def rows(days: int = 49) -> pd.DataFrame:
    """Two stations, a forecast issued every 3 hours with 24 hours ahead each."""
    issues = pd.date_range(START, START + timedelta(days=days), freq="3h", inclusive="left")
    frame = pd.DataFrame(
        [
            {"station": station, "sensor_id": i, "issue_time": issue, "horizon": horizon}
            for i, station in enumerate(["A", "B"])
            for issue in issues
            for horizon in range(1, 25)
        ]
    )
    frame["target_time"] = frame["issue_time"] + pd.to_timedelta(frame["horizon"], unit="h")
    frame["official"] = 10.0
    frame["official_now"] = 12.0  # persistence is always 2 off
    frame["official_day_before"] = 10.0 + frame["horizon"] / 6  # worse further ahead
    return frame


class Recording:
    """Remembers what each fold trained on and forecast, and predicts the training mean."""

    name = "recording"
    has_range = True
    folds: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def fit(self, train: pd.DataFrame) -> None:
        self.mean = float(train["official"].mean())
        self.newest_target = train["target_time"].max()

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        Recording.folds.append((self.newest_target, frame["issue_time"].min()))
        # Deliberately crossed: the harness must put them in order
        return pd.DataFrame(
            {"p10": self.mean + 1, "p50": self.mean, "p90": self.mean - 1}, frame.index
        )


def test_final_test_is_split_off_with_no_shared_labels() -> None:
    frame = rows()

    development, final = split_final_test(frame, FINAL_TEST_START)

    assert (development["target_time"] < pd.Timestamp(FINAL_TEST_START)).all()
    assert (final["issue_time"] >= pd.Timestamp(FINAL_TEST_START)).all()
    # Issued the day before the final test, with a target inside it: in neither part
    assert len(development) + len(final) < len(frame)


def test_each_fold_learns_only_from_targets_before_it() -> None:
    development, _ = split_final_test(rows(), FINAL_TEST_START)
    Recording.folds = []

    report = backtest(Recording, development, FINAL_TEST_START)

    assert len(Recording.folds) == FOLDS
    for (newest_target, first_issue), start in zip(
        Recording.folds, fold_starts(FINAL_TEST_START), strict=True
    ):
        assert newest_target < pd.Timestamp(start) <= first_issue
    assert report.coverage == 1.0  # the crossed range was sorted, and 10 is inside 9 to 11


def test_baselines_are_scored_per_station_and_by_hours_ahead() -> None:
    development, _ = split_final_test(rows(), FINAL_TEST_START)

    persistence = backtest(Persistence, development, FINAL_TEST_START)
    yesterday = backtest(SameHourYesterday, development, FINAL_TEST_START)

    assert persistence.headline_mae == pytest.approx(2.0)
    assert persistence.coverage is None  # a point forecast has no range
    assert yesterday.groups["1-6h"] < yesterday.groups["13-24h"]
    assert set(persistence.stations) == {"A", "B"}


def test_pinball_loss_charges_misses_by_their_quantile() -> None:
    official = pd.Series([10.0, 10.0])
    predicted = pd.Series([8.0, 12.0])  # 2 too low, then 2 too high

    np.testing.assert_allclose(pinball_loss(official, predicted, 0.9), [1.8, 0.2])
    np.testing.assert_allclose(pinball_loss(official, predicted, 0.1), [0.2, 1.8])


def test_score_counts_hours_inside_the_range() -> None:
    predictions = pd.DataFrame(
        {
            "station": ["A"] * 4,
            "horizon": [1, 2, 3, 4],
            "official": [5.0, 10.0, 15.0, 20.0],
            "p10": 8.0,
            "p50": 12.0,
            "p90": 16.0,
        }
    )

    report = score("m", True, predictions)

    assert report.coverage == 0.5  # 10 and 15 are inside 8 to 16


def report(mae: float, groups: list[float], coverage: float | None) -> ForecastReport:
    names = ["1-6h", "7-12h", "13-24h"]
    return ForecastReport("m", 100, mae, dict(zip(names, groups, strict=True)), {}, coverage, 1.0)


def test_ship_rules() -> None:
    persistence = report(3.0, [1.5, 3.0, 4.0], None)
    yesterday = report(3.5, [3.5, 3.5, 3.5], None)

    assert ship_check(report(2.5, [1.6, 2.5, 3.0], 0.80), persistence, yesterday) == []
    failures = ship_check(report(3.1, [1.6, 3.2, 3.0], 0.70), persistence, yesterday)
    assert len(failures) == 3  # MAE, only 1 of 3 groups, and a range that is too narrow
