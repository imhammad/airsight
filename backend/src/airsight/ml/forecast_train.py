"""Train the air quality forecast and track every run in MLflow (ADR 0012).

Three LightGBM models, one per quantile (p10, p50 and p90), learn from the same rows with the
hours ahead as a feature. They are backtested with the same harness and the same folds as the
two baselines, and the ship rules decide whether the run is good enough to promote. Then one
set of models is fitted on all development data and stored with the run, as one MLflow model
that holds all three and their widening, so they can only ever be versioned and served together.

Quantile models trained on the past come out overconfident on the future: their p10 to p90 range
holds fewer than 8 hours in 10. So each fit is calibrated (conformalized quantile regression):
the models first learn from all but the newest week, the miss on that week sets how far to
widen the range for each hour ahead, and then the models learn from every row.

Run from backend/ with the stack up:  uv run python -m airsight.ml.forecast_train
"""

import argparse
import json
import logging
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
from mlflow.pyfunc.model import PythonModel, PythonModelContext

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
CALIBRATION_DAYS = 7  # the newest week of training rows sets how far to widen the range
COVERAGE = 0.8  # what p10 to p90 should hold


def widening(predicted: pd.DataFrame, official: pd.Series, horizon: pd.Series) -> dict[int, float]:
    """How far to move p10 down and p90 up, for each hour ahead, so 80% of hours fall inside.

    The score of an hour is how far outside the range it fell (negative when inside). Moving both
    ends by the 80th percentile of those scores puts 80% of the hours inside. A range that was
    too wide gets a negative widening, which narrows it.
    """
    outside = pd.Series(
        np.maximum(predicted["p10"] - official, official - predicted["p90"]), index=official.index
    )
    return {int(h): float(np.quantile(group, COVERAGE)) for h, group in outside.groupby(horizon)}


class QuantileLightGbm:
    """p10, p50 and p90 of the monitor's reading, from the features in forecast_features.py."""

    name = "lightgbm_quantile"
    has_range = True

    boosters: dict[str, lgb.Booster]
    widen: dict[int, float]  # hours ahead -> how far to move p10 down and p90 up

    def _fit_boosters(self, train: pd.DataFrame) -> dict[str, lgb.Booster]:
        data = lgb.Dataset(train[FORECAST_FEATURES], label=train[TARGET], free_raw_data=False)
        return {
            name: lgb.train({**PARAMS, "alpha": quantile}, data, num_boost_round=ROUNDS)
            for name, quantile in QUANTILES.items()
        }

    def _raw_predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        features = frame[FORECAST_FEATURES]
        predicted = pd.DataFrame(
            {name: booster.predict(features) for name, booster in self.boosters.items()},
            index=frame.index,
        )
        ordered = np.sort(predicted[list(QUANTILES)].to_numpy(), axis=1)
        return pd.DataFrame(ordered, columns=list(QUANTILES), index=frame.index)

    def fit(self, train: pd.DataFrame) -> None:
        # Calibrate on the newest week, purged like a fold: learn only from targets before it
        start = train["issue_time"].max() - timedelta(days=CALIBRATION_DAYS)
        proper = train[train["target_time"] < start]
        calibration = train[train["issue_time"] >= start]
        self.boosters = self._fit_boosters(proper)
        self.widen = widening(
            self._raw_predict(calibration), calibration[TARGET], calibration["horizon"]
        )
        self.boosters = self._fit_boosters(train)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        predicted = self._raw_predict(frame)
        widen = frame["horizon"].map(self.widen).fillna(0.0)
        predicted["p10"] = (predicted["p10"] - widen).clip(lower=0.0)  # PM2.5 is never below 0
        predicted["p90"] = predicted["p90"] + widen
        return predicted


class ForecastBundle(PythonModel):
    """The three quantile models and their widening, stored and loaded as one MLflow model."""

    model: QuantileLightGbm

    def load_context(self, context: PythonModelContext) -> None:
        model = QuantileLightGbm()
        model.boosters = {
            name: lgb.Booster(model_file=context.artifacts[name]) for name in QUANTILES
        }
        widen = json.loads(Path(context.artifacts["widening"]).read_text())
        model.widen = {int(h): float(w) for h, w in widen.items()}
        self.model = model

    def predict(
        self,
        context: PythonModelContext,
        model_input: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Columns p10, p50 and p90 (calibrated, in order) for rows with FORECAST_FEATURES."""
        return self.model.predict(model_input)


def bundle_input(frame: pd.DataFrame) -> pd.DataFrame:
    """What the stored model takes: the features as floats, so a missing value is allowed."""
    return frame[FORECAST_FEATURES].astype("float64")


def log_bundle(model: QuantileLightGbm, example: pd.DataFrame) -> str:
    """Store a fitted model as one MLflow model in the active run. Returns its model URI."""
    with tempfile.TemporaryDirectory() as directory:
        artifacts = {}
        for name, booster in model.boosters.items():
            path = Path(directory) / f"{name}.txt"
            booster.save_model(str(path))
            artifacts[name] = str(path)
        widening_file = Path(directory) / "widening.json"
        widening_file.write_text(json.dumps({str(h): w for h, w in model.widen.items()}))
        artifacts["widening"] = str(widening_file)
        logged = mlflow.pyfunc.log_model(
            name="model", python_model=ForecastBundle(), artifacts=artifacts, input_example=example
        )
    return str(logged.model_uri)


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
        example = bundle_input(development.head(5))
        mlflow.set_tag("model_uri", log_bundle(final_model, example))  # what promotion registers

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
