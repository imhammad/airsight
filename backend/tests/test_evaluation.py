import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from airsight.ml.evaluation import (
    EpaBaseline,
    Metrics,
    RawBaseline,
    Report,
    evaluate,
    evaluate_validation,
    leave_one_station_out,
    score,
    ship_check,
    split_final_test,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


def pairs(station: str, hours: int, raw: float, official: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station": station,
            "sensor_id": ord(station[0]),
            "time": [START + timedelta(hours=h) for h in range(hours)],
            "raw": raw,
            "sensor_humidity": 50.0,
            "official": official,
        }
    )


class RecordingModel:
    """Remembers which stations it was trained on, and predicts the training mean."""

    name = "recording"
    trained_on: list[set[str]] = []

    def fit(self, train: pd.DataFrame) -> None:
        RecordingModel.trained_on.append(set(train["station"]))
        self.mean = float(train["official"].mean())

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        return pd.Series(self.mean, index=frame.index)


def test_each_station_is_predicted_by_a_model_that_never_saw_it() -> None:
    frame = pd.concat([pairs("A", 5, 10, 8), pairs("B", 5, 10, 6), pairs("C", 5, 10, 4)])
    RecordingModel.trained_on = []

    predictions = leave_one_station_out(RecordingModel, frame, frame)

    assert RecordingModel.trained_on == [{"B", "C"}, {"A", "C"}, {"A", "B"}]
    assert predictions.groupby("station")["predicted"].first().to_dict() == {
        "A": 5.0,
        "B": 6.0,
        "C": 7.0,
    }


def test_headline_is_the_mean_of_stations_not_of_rows() -> None:
    # A busy station with error 1 and a quiet one with error 5
    busy = pairs("Busy", 900, raw=11, official=10)
    quiet = pairs("Quiet", 100, raw=15, official=10)
    predictions = pd.concat([busy, quiet]).assign(predicted=lambda f: f["raw"])

    report = score("raw", predictions)

    assert report.headline_mae == pytest.approx(3.0)  # (1 + 5) / 2
    assert report.overall.mae == pytest.approx(1.4)  # what a row average would hide behind
    assert report.stations["Quiet"] == Metrics(hours=100, mae=5.0, bias=5.0, rmse=5.0)


def test_hours_are_banded_by_the_official_reading() -> None:
    predictions = pd.DataFrame(
        {
            "station": "A",
            "official": [0.0, 9.0, 9.1, 35.4, 40.0],
            "predicted": [1.0, 9.0, 9.1, 35.4, 40.0],
        }
    )

    bands = score("x", predictions).bands

    assert {band: m.hours for band, m in bands.items()} == {"good": 2, "moderate": 2, "high": 1}


def test_baselines() -> None:
    frame = pd.DataFrame({"raw": [10.0], "sensor_humidity": [50.0]})

    assert RawBaseline().predict(frame).iloc[0] == 10.0
    assert EpaBaseline().predict(frame).iloc[0] == pytest.approx(0.524 * 10 - 0.0862 * 50 + 5.75)


def test_final_test_period_is_split_off() -> None:
    frame = pairs("A", 48, 10, 8)

    development, final = split_final_test(frame, START + timedelta(hours=24))

    assert len(development) == 24
    assert len(final) == 24
    assert final["time"].min() == START + timedelta(hours=24)


def report(headline: float, moderate_mae: float, station_maes: list[float]) -> Report:
    metric = Metrics(hours=500, mae=moderate_mae, bias=0.0, rmse=0.0)
    return Report(
        model="m",
        headline_mae=headline,
        overall=metric,
        stations={
            f"S{i}": Metrics(hours=500, mae=mae, bias=0.0, rmse=0.0)
            for i, mae in enumerate(station_maes)
        },
        bands={"good": metric, "moderate": metric, "high": metric},
    )


def test_ship_rules() -> None:
    raw = report(3.6, moderate_mae=4.0, station_maes=[4, 4, 4, 4])
    epa = report(3.2, moderate_mae=5.0, station_maes=[3, 3, 3, 3])

    assert ship_check(report(2.9, 3.9, [2, 2, 2, 4]), raw, epa) == []
    failures = ship_check(report(3.3, 4.5, [2, 2, 4, 4]), raw, epa)
    assert len(failures) == 3  # headline, moderate MAE above raw, and only 2 of 4 stations


def test_evaluate_scores_baselines_on_a_dataset_file(tmp_path: Path) -> None:
    frame = pd.concat([pairs("A", 48, 10, 8), pairs("B", 48, 12, 9)])
    path = tmp_path / "pairs-test.parquet"
    frame.to_parquet(path, index=False)
    final_start = START + timedelta(hours=36)
    path.with_suffix(".json").write_text(json.dumps({"final_test_start": final_start.isoformat()}))

    development = evaluate(path, [RawBaseline, EpaBaseline])
    final = evaluate(path, [RawBaseline], final=True)

    assert [r.model for r in development] == ["raw", "epa"]
    assert development[0].overall.hours == 72
    assert development[0].headline_mae == pytest.approx(2.5)  # (2 + 3) / 2
    assert final[0].overall.hours == 24


class NewestHourModel:
    """Remembers the newest hour it was trained on, and predicts zero."""

    name = "newest"
    newest: list[pd.Timestamp] = []

    def fit(self, train: pd.DataFrame) -> None:
        NewestHourModel.newest.append(train["time"].max())

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=frame.index)


def test_validation_is_the_14_days_before_the_final_test(tmp_path: Path) -> None:
    hours = 30 * 24
    frame = pd.concat([pairs("A", hours, 10, 8), pairs("B", hours, 12, 9)])
    path = tmp_path / "pairs-test.parquet"
    frame.to_parquet(path, index=False)
    final_start = START + timedelta(days=28)
    path.with_suffix(".json").write_text(json.dumps({"final_test_start": final_start.isoformat()}))

    (report,) = evaluate_validation(path, [NewestHourModel])

    assert report.overall.hours == 2 * 14 * 24  # days 14 to 27 of both stations
    assert max(NewestHourModel.newest) < START + timedelta(days=14)  # trained before them
