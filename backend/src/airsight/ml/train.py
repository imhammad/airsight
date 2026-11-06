"""Train the LightGBM correction model and track every run in MLflow.

Each run scores the model and both baselines with the ADR 0007 harness on the development
period, logs the numbers, the dataset hash and the parameters to MLflow, then fits one model on
all development data and stores it with the run.

Run from backend/ with the stack up:  uv run python -m airsight.ml.train
"""

import argparse
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import mlflow
import pandas as pd

from airsight.core.config import get_settings
from airsight.core.logging import configure_logging
from airsight.ml.evaluation import (
    EpaBaseline,
    RawBaseline,
    Report,
    evaluate,
    format_report,
    latest_dataset,
    ship_check,
    split_final_test,
)
from airsight.ml.features import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

EXPERIMENT = "correction"
TARGET = "official"

# Chosen for ~50k rows and 9 features; tuning comes later, and is tracked when it does
PARAMS: dict[str, Any] = {
    "objective": "l1",  # we are judged on MAE, so train on absolute error
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 50,  # no leaf for a handful of odd hours
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "feature_fraction": 0.9,
    "seed": 42,
    "verbose": -1,
}
ROUNDS = 400


class LightGbmModel:
    """Predicts the official reading from the features in ml/features.py."""

    name = "lightgbm"

    booster: lgb.Booster

    def fit(self, train: pd.DataFrame) -> None:
        data = lgb.Dataset(train[FEATURE_COLUMNS], label=train[TARGET])
        self.booster = lgb.train(PARAMS, data, num_boost_round=ROUNDS)

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        return pd.Series(self.booster.predict(frame[FEATURE_COLUMNS]), index=frame.index)


def report_metrics(report: Report) -> dict[str, float]:
    """Flatten a report into MLflow metric names, such as lightgbm.station.Oakland.mae."""
    prefix = report.model
    values = {f"{prefix}.headline_mae": report.headline_mae}
    for name, metric in [("all", report.overall), *report.bands.items()]:
        values |= {
            f"{prefix}.{name}.mae": metric.mae,
            f"{prefix}.{name}.bias": metric.bias,
            f"{prefix}.{name}.hours": float(metric.hours),
        }
    for station, metric in report.stations.items():
        key = "".join(c if c.isalnum() else "_" for c in station)  # MLflow-safe name
        values[f"{prefix}.station.{key}.mae"] = metric.mae
    return values


def train(dataset: Path) -> str:
    """One tracked training run. Returns the MLflow run id."""
    info = json.loads(dataset.with_suffix(".json").read_text())
    raw, epa, model = evaluate(dataset, [RawBaseline, EpaBaseline, LightGbmModel])
    failures = ship_check(model, raw, epa)

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run() as run:
        mlflow.set_tags(
            {"dataset": info["content_hash"], "period": "development", "ships": not failures}
        )
        mlflow.log_params({**PARAMS, "rounds": ROUNDS, "features": ",".join(FEATURE_COLUMNS)})
        mlflow.log_params({"dataset_rows": info["rows"], "dataset_start": info["start"]})
        for report in (raw, epa, model):
            mlflow.log_metrics(report_metrics(report))
        mlflow.log_dict({"reports": [asdict(r) for r in (raw, epa, model)]}, "reports.json")
        mlflow.log_text("\n".join(failures) or "passes every ship rule", "ship_check.txt")

        # The model we keep is fitted on all development data, never on the final test period
        development, _ = split_final_test(
            pd.read_parquet(dataset), datetime.fromisoformat(info["final_test_start"])
        )
        final_model = LightGbmModel()
        final_model.fit(development)
        logged = mlflow.lightgbm.log_model(
            final_model.booster,
            name="model",
            # Floats in the signature, so a missing weather value at serving time is allowed
            input_example=development[FEATURE_COLUMNS].head(5).astype("float64"),
        )
        mlflow.set_tag("model_uri", logged.model_uri)  # what the registry promotes

    for report in (raw, epa, model):
        print(format_report(report), end="\n\n")
    print("Ship rules (development period):", "; ".join(failures) or "all pass")
    return str(run.info.run_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, help="Parquet file (default: the newest one)")
    args = parser.parse_args()
    configure_logging()
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    run_id = train(args.dataset or latest_dataset())
    logger.info("MLflow run %s", run_id)


if __name__ == "__main__":
    main()
