import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest

from airsight.ml.evaluation import RawBaseline, leave_one_station_out, score
from airsight.ml.features import FEATURE_COLUMNS
from airsight.ml.train import CANDIDATES, LightGbmModel, report_metrics, train, training_rows

START = datetime(2026, 9, 1, tzinfo=UTC)


def synthetic_pairs(hours: int = 600) -> pd.DataFrame:
    """Sensors that read 40% high, more so when humid: a pattern a model should learn."""
    rng = np.random.default_rng(0)
    rows = []
    for station in ["A", "B", "C"]:
        official = rng.gamma(2.0, 4.0, hours)
        humidity = rng.uniform(30, 95, hours)
        raw = official * (1.4 + (humidity - 30) / 100) + rng.normal(0, 0.5, hours)
        frame = pd.DataFrame(
            {
                "station": station,
                "sensor_id": ord(station),
                "time": [START + timedelta(hours=h) for h in range(hours)],
                "official": official,
                "raw": raw,
                "sensor_humidity": humidity,
            }
        )
        for column in FEATURE_COLUMNS:
            if column not in frame:
                frame[column] = 0.0
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def test_model_learns_what_raw_gets_wrong() -> None:
    frame = synthetic_pairs()

    model = score("lightgbm", leave_one_station_out(LightGbmModel, frame, frame))
    raw = score("raw", leave_one_station_out(RawBaseline, frame, frame))

    assert model.headline_mae < raw.headline_mae / 3


def test_candidates_learn_from_different_rows() -> None:
    frame = synthetic_pairs(90 * 24)
    newest = frame["time"].max()

    every_row, no_weights = training_rows(frame, CANDIDATES["all-data"])
    recent, _ = training_rows(frame, CANDIDATES["last-60-days"])
    weighted, weights = training_rows(frame, CANDIDATES["recent-weighted"])

    assert len(every_row) == len(frame)
    assert no_weights is None
    assert recent["time"].min() > newest - timedelta(days=60)
    assert len(weighted) == len(frame)
    assert weights is not None
    assert weights[weighted["time"] == newest].tolist() == [1.0, 1.0, 1.0]
    month_old = weights[weighted["time"] == newest - timedelta(days=30)]
    assert month_old.tolist() == pytest.approx([0.5, 0.5, 0.5])  # halves every 30 days


def test_metric_names_are_mlflow_safe() -> None:
    frame = synthetic_pairs(200).replace({"station": {"A": "San Pablo - Rumrill"}})
    report = score("raw", leave_one_station_out(RawBaseline, frame, frame))

    names = report_metrics(report)

    assert "raw.headline_mae" in names
    assert "raw.station.San_Pablo___Rumrill.mae" in names
    assert "raw.moderate.hours" in names


@pytest.fixture
def local_mlflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # MLflow writes model files to ./mlruns next to a local database: keep them in tmp_path
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    mlflow.set_tracking_uri(uri)
    return uri


def test_training_run_is_tracked(local_mlflow: str, tmp_path: Path) -> None:
    frame = synthetic_pairs()
    dataset = tmp_path / "pairs-test.parquet"
    frame.to_parquet(dataset, index=False)
    final_start = START + timedelta(hours=500)
    dataset.with_suffix(".json").write_text(
        json.dumps(
            {
                "content_hash": "test",
                "rows": len(frame),
                "start": START.isoformat(),
                "final_test_start": final_start.isoformat(),
            }
        )
    )

    run_id = train(dataset)

    run = mlflow.get_run(run_id)
    assert run.data.tags["dataset"] == "test"
    assert run.data.tags["ships"] == "True"
    # ADR 0011: all three candidates were scored on validation, and the best one was kept
    validation = {name: run.data.metrics[f"validation.{name}.headline_mae"] for name in CANDIDATES}
    assert validation[run.data.tags["candidate"]] == min(validation.values())
    assert run.data.metrics["lightgbm.headline_mae"] < run.data.metrics["epa.headline_mae"]
    loaded = mlflow.lightgbm.load_model(f"runs:/{run_id}/model")
    assert len(loaded.predict(frame[FEATURE_COLUMNS].head(3))) == 3
