import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest

from airsight.ml.forecast_evaluation import Persistence, backtest, split_final_test
from airsight.ml.forecast_features import FORECAST_FEATURES, forecast_rows
from airsight.ml.forecast_train import QuantileLightGbm, report_metrics, train

START = datetime(2026, 6, 1, tzinfo=UTC)
DAYS = 50
END = START + timedelta(days=DAYS)
FINAL_TEST_START = END - timedelta(days=7)


def synthetic_rows() -> pd.DataFrame:
    """Two stations with a strong daily cycle, which persistence can't follow and a model can."""
    rng = np.random.default_rng(0)
    times = pd.date_range(START, END, freq="h", inclusive="left")
    sensor_hours, official, weather = [], [], []
    for station in (1, 2):
        cycle = 4 * np.cos(2 * np.pi * (times.hour - 4) / 24)
        values = np.clip(8 + cycle + rng.normal(0, 0.7, len(times)), 0, None)
        official.append(pd.DataFrame({"station_id": station, "time": times, "official": values}))
        sensor_hours.append(
            pd.DataFrame(
                {
                    "sensor_id": station * 10,
                    "station_id": station,
                    "station": f"Station {station}",
                    "cell_id": "cell",
                    "time": times,
                    "raw": values * 1.4,
                }
            )
        )
    weather.append(
        pd.DataFrame(
            {
                "cell_id": "cell",
                "time": times,
                "temperature": 15.0,
                "relative_humidity": 70.0,
                "wind_speed": 5.0,
                "wind_direction": 270.0,
                "precipitation": 0.0,
            }
        )
    )
    rows = forecast_rows(
        pd.concat(sensor_hours), pd.concat(official), pd.concat(weather), START, END
    )
    return rows[rows["official"].notna()].reset_index(drop=True)


def test_quantile_models_beat_persistence_and_give_a_range() -> None:
    development, _ = split_final_test(synthetic_rows(), FINAL_TEST_START)

    model = backtest(QuantileLightGbm, development, FINAL_TEST_START)
    persistence = backtest(Persistence, development, FINAL_TEST_START)

    assert model.headline_mae < persistence.headline_mae / 2
    assert model.coverage is not None
    assert 0.6 < model.coverage < 0.95  # p10 to p90 should hold about 80% of hours


def test_metric_names_are_mlflow_safe() -> None:
    development, _ = split_final_test(synthetic_rows(), FINAL_TEST_START)
    report = backtest(Persistence, development, FINAL_TEST_START)

    names = report_metrics(report)

    assert "persistence.headline_mae" in names
    assert "persistence.horizon.1-6h.mae" in names
    assert "persistence.station.Station_1.mae" in names
    assert "persistence.coverage" not in names  # a point forecast has no range


@pytest.fixture
def local_mlflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # MLflow writes model files to ./mlruns next to a local database: keep them in tmp_path
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    mlflow.set_tracking_uri(uri)
    return uri


def test_training_run_is_tracked(local_mlflow: str, tmp_path: Path) -> None:
    frame = synthetic_rows()
    dataset = tmp_path / "forecast-test.parquet"
    frame.to_parquet(dataset, index=False)
    dataset.with_suffix(".json").write_text(
        json.dumps(
            {
                "content_hash": "test",
                "rows": len(frame),
                "start": START.isoformat(),
                "final_test_start": FINAL_TEST_START.isoformat(),
            }
        )
    )

    run_id = train(dataset)

    run = mlflow.get_run(run_id)
    assert run.data.tags["dataset"] == "test"
    assert run.data.tags["period"] == "backtest"
    metrics = run.data.metrics
    assert metrics["lightgbm_quantile.headline_mae"] < metrics["persistence.headline_mae"]
    for name in ("p10", "p50", "p90"):
        loaded = mlflow.lightgbm.load_model(run.data.tags[f"model_uri.{name}"])
        assert len(loaded.predict(frame[FORECAST_FEATURES].head(3))) == 3
