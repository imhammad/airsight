"""Train the air quality forecast and track every run in MLflow (ADR 0012).

Three LightGBM models, one per quantile (p10, p50 and p90), learn from the same rows with the
hours ahead as a feature. They are backtested with the same harness and the same folds as the
two baselines, and the ship rules decide whether the run is good enough to promote. Then one
set of models is fitted on all development data and stored with the run.

Run from backend/ with the stack up:  uv run python -m airsight.ml.forecast_train
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
from airsight.ml.forecast_evaluation import (
    BASELINES,
    QUANTILES,
    ForecastReport,
    evaluate,
    format_report,
    latest_forecast_dataset,
    ship_check,
    split_final_test,
)
from airsight.ml.forecast_features import FORECAST_FEATURES, TARGET

logger = logging.getLogger(__name__)

EXPERIMENT = "forecast"

# Chosen for ~400k rows and 13 features; tuning comes later, and is tracked when it does
PARAMS: dict[str, Any] = {
    "objective": "quantile",  # each model learns one quantile; "alpha" says which
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 200,  # forecast rows come 24 to an issue hour, so leaves need more
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "feature_fraction": 0.9,
    "seed": 42,
    "verbose": -1,
}
ROUNDS = 300


class QuantileLightGbm:
    """p10, p50 and p90 of the monitor's reading, from the features in forecast_features.py."""

    name = "lightgbm_quantile"
    has_range = True

    boosters: dict[str, lgb.Booster]

    def fit(self, train: pd.DataFrame) -> None:
        data = lgb.Dataset(train[FORECAST_FEATURES], label=train[TARGET], free_raw_data=False)
        self.boosters = {
            name: lgb.train({**PARAMS, "alpha": quantile}, data, num_boost_round=ROUNDS)
            for name, quantile in QUANTILES.items()
        }

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        features = frame[FORECAST_FEATURES]
        return pd.DataFrame(
            {name: booster.predict(features) for name, booster in self.boosters.items()},
            index=frame.index,
        )


def report_metrics(report: ForecastReport) -> dict[str, float]:
    """Flatten a report into MLflow metric names, such as persistence.horizon.1-6h.mae."""
    prefix = report.model
    values = {f"{prefix}.headline_mae": report.headline_mae, f"{prefix}.pinball": report.pinball}
    if report.coverage is not None:
        values[f"{prefix}.coverage"] = report.coverage
    for group, mae in report.groups.items():
        values[f"{prefix}.horizon.{group}.mae"] = mae
    for station, mae in report.stations.items():
        key = "".join(c if c.isalnum() else "_" for c in station)  # MLflow-safe name
        values[f"{prefix}.station.{key}.mae"] = mae
    return values


def train(dataset: Path) -> str:
    """One tracked training run. Returns the MLflow run id."""
    info = json.loads(dataset.with_suffix(".json").read_text())
    persistence, yesterday, model = evaluate(dataset, [*BASELINES, QuantileLightGbm])
    failures = ship_check(model, persistence, yesterday)

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run() as run:
        mlflow.set_tags(
            {"dataset": info["content_hash"], "period": "backtest", "ships": not failures}
        )
        mlflow.log_params({**PARAMS, "rounds": ROUNDS, "features": ",".join(FORECAST_FEATURES)})
        mlflow.log_params({"dataset_rows": info["rows"], "dataset_start": info["start"]})
        for report in (persistence, yesterday, model):
            mlflow.log_metrics(report_metrics(report))
        mlflow.log_dict(
            {"reports": [asdict(r) for r in (persistence, yesterday, model)]}, "reports.json"
        )
        mlflow.log_text("\n".join(failures) or "passes every ship rule", "ship_check.txt")

        # The models we keep are fitted on all development data, never on the final test period
        development, _ = split_final_test(
            pd.read_parquet(dataset), datetime.fromisoformat(info["final_test_start"])
        )
        final_model = QuantileLightGbm()
        final_model.fit(development)
        example = development[FORECAST_FEATURES].head(5).astype("float64")
        for name, booster in final_model.boosters.items():
            logged = mlflow.lightgbm.log_model(booster, name=name, input_example=example)
            mlflow.set_tag(f"model_uri.{name}", logged.model_uri)

    for report in (persistence, yesterday, model):
        print(format_report(report))
    print("\nShip rules (backtest):", "; ".join(failures) or "all pass")
    return str(run.info.run_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, help="Parquet file (default: the newest one)")
    args = parser.parse_args()
    configure_logging()
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    run_id = train(args.dataset or latest_forecast_dataset())
    logger.info("MLflow run %s", run_id)


if __name__ == "__main__":
    main()
