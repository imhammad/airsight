import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest
from mlflow import MlflowClient

from airsight.ml import forecast_registry
from airsight.ml.forecast_evaluation import Persistence, backtest, split_final_test
from airsight.ml.forecast_features import forecast_rows
from airsight.ml.forecast_registry import MODEL_NAME, load_champion_version, promote
from airsight.ml.forecast_train import (
    QuantileLightGbm,
    bundle_input,
    report_metrics,
    train,
    widening,
)
from airsight.ml.registry import PromotionRefusedError

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


def test_widening_puts_80_percent_of_hours_inside_the_range() -> None:
    official = pd.Series(np.arange(100, dtype=float))  # 0 to 99, all at 1 hour ahead
    narrow = pd.DataFrame({"p10": 45.0, "p50": 50.0, "p90": 55.0}, index=official.index)

    widen = widening(narrow, official, pd.Series(1, index=official.index))

    inside = official.between(narrow["p10"] - widen[1], narrow["p90"] + widen[1])
    assert inside.mean() == pytest.approx(0.8, abs=0.02)
    wide = pd.DataFrame({"p10": -100.0, "p50": 50.0, "p90": 200.0}, index=official.index)
    assert widening(wide, official, pd.Series(1, index=official.index))[1] < 0  # narrows


def test_calibrated_range_never_goes_below_zero() -> None:
    development, _ = split_final_test(synthetic_rows(), FINAL_TEST_START)
    model = QuantileLightGbm()
    model.fit(development)

    predicted = model.predict(development.head(500))

    assert set(model.widen) == set(range(1, 25))
    assert (predicted["p10"] >= 0).all()
    assert (predicted["p10"] <= predicted["p50"]).all()


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


def trained_run(tmp_path: Path) -> tuple[str, pd.DataFrame]:
    """A training run on the synthetic rows, with its dataset in tmp_path."""
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
    return train(dataset), frame


def test_training_run_is_tracked(local_mlflow: str, tmp_path: Path) -> None:
    run_id, frame = trained_run(tmp_path)

    run = mlflow.get_run(run_id)
    assert run.data.tags["dataset"] == "test"
    assert run.data.tags["period"] == "backtest"
    metrics = run.data.metrics
    assert metrics["lightgbm_quantile.headline_mae"] < metrics["persistence.headline_mae"]
    bundle = mlflow.pyfunc.load_model(run.data.tags["model_uri"])
    predicted = pd.DataFrame(bundle.predict(bundle_input(frame.head(48))))
    assert list(predicted.columns) == ["p10", "p50", "p90"]
    assert (predicted["p10"] <= predicted["p50"]).all()
    assert (predicted["p50"] <= predicted["p90"]).all()


def test_promotion_scores_the_stored_model_and_makes_it_champion(
    local_mlflow: str, tmp_path: Path
) -> None:
    run_id, frame = trained_run(tmp_path)

    version = promote(run_id, datasets_dir=tmp_path)

    bundle, name = load_champion_version()
    assert name == f"{MODEL_NAME}/{version}"
    tags = MlflowClient().get_model_version(MODEL_NAME, str(version)).tags
    assert tags["trained_before"] == FINAL_TEST_START.isoformat()
    run = mlflow.get_run(run_id)
    assert run.data.tags["final_ships"] == "True"
    assert "final.lightgbm_quantile.coverage" in run.data.metrics
    predicted = pd.DataFrame(bundle.predict(bundle_input(frame.head(24))))
    assert (predicted["p10"] <= predicted["p90"]).all()

    with pytest.raises(PromotionRefusedError, match="champion exists"):
        promote(run_id, datasets_dir=tmp_path)  # never replaced without a head-to-head


def test_a_model_that_fails_the_ship_rules_is_not_registered(
    local_mlflow: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _ = trained_run(tmp_path)
    monkeypatch.setattr(forecast_registry, "ship_check", lambda *_: ["too narrow"])

    with pytest.raises(PromotionRefusedError, match="too narrow"):
        promote(run_id, datasets_dir=tmp_path)

    assert mlflow.get_run(run_id).data.tags["final_ships"] == "False"
    assert MlflowClient().search_model_versions(f"name = '{MODEL_NAME}'") == []
