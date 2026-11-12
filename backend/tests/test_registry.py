import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest

from airsight.ml import registry
from airsight.ml.features import FEATURE_COLUMNS, INPUT_COLUMNS, add_features
from airsight.ml.predict import correct
from airsight.ml.registry import (
    CHAMPION,
    MODEL_NAME,
    PromotionRefusedError,
    load_champion,
    promote,
)
from airsight.ml.train import train

START = datetime(2026, 9, 1, tzinfo=UTC)


def write_dataset(
    directory: Path,
    name: str,
    raw_is_perfect: bool = False,
    hours: int = 700,
    final_test_hour: int = 500,
    drift_from: int | None = None,
) -> Path:
    """Four stations whose sensors read high when humid; or, if raw_is_perfect, never wrong.

    From hour drift_from on, the sensors read even higher, as if their air or optics changed.
    """
    rng = np.random.default_rng(1)
    frames = []
    for station in ["A", "B", "C", "D"]:
        official = rng.gamma(2.0, 6.0, hours)
        humidity = rng.uniform(30, 95, hours)
        factor = 1.4 + (humidity - 30) / 100
        if drift_from is not None:
            factor = np.where(np.arange(hours) >= drift_from, factor + 0.8, factor)
        raw = official if raw_is_perfect else official * factor
        frames.append(
            pd.DataFrame(
                {
                    "station": station,
                    "sensor_id": ord(station),
                    "time": [START + timedelta(hours=h) for h in range(hours)],
                    "official": official,
                    "pm25_a": raw,
                    "pm25_b": raw,
                    "humidity": humidity,
                    "temperature": 15.0,
                    "relative_humidity": humidity,
                    "wind_speed": 5.0,
                    "precipitation": 0.0,
                }
            )
        )
    frame = add_features(pd.concat(frames, ignore_index=True))
    path = directory / f"pairs-{name}.parquet"
    frame.to_parquet(path, index=False)
    info = {
        "content_hash": name,
        "rows": len(frame),
        "start": START.isoformat(),
        "final_test_start": (START + timedelta(hours=final_test_hour)).isoformat(),
    }
    path.with_suffix(".json").write_text(json.dumps(info))
    return path


@pytest.fixture
def local_mlflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # MLflow writes model files to ./mlruns
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")


def test_passing_model_becomes_champion(local_mlflow: None, tmp_path: Path) -> None:
    run_id = train(write_dataset(tmp_path, "good"))

    version = promote(run_id, datasets_dir=tmp_path)

    assert version == 1
    client = mlflow.MlflowClient()
    champion = client.get_model_version_by_alias(MODEL_NAME, CHAMPION)
    assert int(champion.version) == 1
    assert champion.tags["trained_before"] == (START + timedelta(hours=500)).isoformat()
    run = client.get_run(run_id)
    assert run.data.tags["final_ships"] == "True"
    assert "final.lightgbm.headline_mae" in run.data.metrics


def test_failing_model_is_not_registered(local_mlflow: None, tmp_path: Path) -> None:
    # Raw is already perfect here, so no model can beat it on moderate hours (rule 2)
    run_id = train(write_dataset(tmp_path, "perfect", raw_is_perfect=True))

    with pytest.raises(PromotionRefusedError, match="moderate MAE"):
        promote(run_id, datasets_dir=tmp_path)

    assert mlflow.MlflowClient().search_registered_models() == []
    assert mlflow.get_run(run_id).data.tags["final_ships"] == "False"


def test_the_final_test_must_be_new_to_the_champion(local_mlflow: None, tmp_path: Path) -> None:
    run_id = train(write_dataset(tmp_path, "good"))
    promote(run_id, datasets_dir=tmp_path)

    # The same 14 days again: the champion was already tested on them
    with pytest.raises(PromotionRefusedError, match="build a dataset that ends"):
        promote(run_id, datasets_dir=tmp_path)

    champion = mlflow.MlflowClient().get_model_version_by_alias(MODEL_NAME, CHAMPION)
    assert int(champion.version) == 1


def test_a_better_model_replaces_the_champion(local_mlflow: None, tmp_path: Path) -> None:
    promote(train(write_dataset(tmp_path, "good")), datasets_dir=tmp_path)
    # The sensors drift after the champion's training data ends, at hour 500
    later = write_dataset(tmp_path, "later", hours=1300, final_test_hour=900, drift_from=500)
    run_id = train(later)

    version = promote(run_id, datasets_dir=tmp_path)

    assert version == 2
    metrics = mlflow.get_run(run_id).data.metrics
    assert metrics["final.candidate.headline_mae"] < metrics["final.champion.headline_mae"]


def test_a_model_no_better_than_the_champion_is_refused(
    local_mlflow: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = train(write_dataset(tmp_path, "good"))
    itself = mlflow.lightgbm.load_model(f"runs:/{run_id}/model")
    # The champion is this very model, trained long ago: an equal score is not an improvement
    monkeypatch.setattr(registry, "current_champion", lambda: (itself, START - timedelta(days=60)))

    with pytest.raises(PromotionRefusedError, match="not below the champion's"):
        promote(run_id, datasets_dir=tmp_path)

    assert mlflow.MlflowClient().search_registered_models() == []


def test_champion_signature_matches_the_features(local_mlflow: None, tmp_path: Path) -> None:
    promote(train(write_dataset(tmp_path, "good")), datasets_dir=tmp_path)

    info = mlflow.models.get_model_info(f"models:/{MODEL_NAME}@{CHAMPION}")

    assert info.signature is not None
    assert info.signature.inputs.input_names() == FEATURE_COLUMNS


def test_serving_matches_training(local_mlflow: None, tmp_path: Path) -> None:
    """Training/serving skew: stored inputs in, the same answers as on the training rows out."""
    dataset = write_dataset(tmp_path, "good")
    promote(train(dataset), datasets_dir=tmp_path)
    booster = load_champion()
    training_rows = pd.read_parquet(dataset)

    served = correct(booster, training_rows[INPUT_COLUMNS])

    expected = booster.predict(training_rows[FEATURE_COLUMNS])
    np.testing.assert_allclose(served.to_numpy(), expected)
