"""Train the LightGBM correction model and track every run in MLflow.

Each run follows ADR 0011. Three candidates, which differ only in the training rows they learn
from, are scored on the validation period (the 14 days before the final test), and the best one
goes forward. It is scored with the ADR 0007 harness on the development period, then one model
is fitted on all development data and stored with the run, along with every score, the dataset
hash and the parameters.

Run from backend/ with the stack up:  uv run python -m airsight.ml.train
"""

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

import lightgbm as lgb
import mlflow
import pandas as pd

from airsight.core.config import get_settings
from airsight.core.logging import configure_logging
from airsight.ml.evaluation import (
    EpaBaseline,
    Model,
    RawBaseline,
    Report,
    evaluate,
    evaluate_validation,
    format_report,
    latest_dataset,
    ship_check,
    split_final_test,
)
from airsight.ml.features import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

EXPERIMENT = "correction"
TARGET = "official"

# Chosen for ~50k rows and 8 features; tuning comes later, and is tracked when it does
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


@dataclass(frozen=True)
class Candidate:
    """Which training rows a model learns from, and how much each one counts (ADR 0011)."""

    name: str
    window_days: int | None = None  # only rows at most this many days older than the newest
    half_life_days: float | None = None  # a row's weight halves for every this many days of age


CANDIDATES = {
    candidate.name: candidate
    for candidate in [
        Candidate("all-data"),
        Candidate("last-60-days", window_days=60),
        Candidate("recent-weighted", half_life_days=30),
    ]
}
ALL_DATA = CANDIDATES["all-data"]  # what v1 was trained with


def training_rows(
    train: pd.DataFrame, candidate: Candidate
) -> tuple[pd.DataFrame, pd.Series | None]:
    """The rows a candidate learns from, and their weights (None: every row counts the same)."""
    age_days = (train["time"].max() - train["time"]).dt.total_seconds() / 86_400
    if candidate.window_days is not None:
        recent = age_days < candidate.window_days
        train, age_days = train[recent], age_days[recent]
    if candidate.half_life_days is None:
        return train, None
    return train, 0.5 ** (age_days / candidate.half_life_days)


class LightGbmModel:
    """Predicts the official reading from the features in ml/features.py."""

    name = "lightgbm"

    booster: lgb.Booster

    def __init__(self, candidate: Candidate = ALL_DATA) -> None:
        self.candidate = candidate

    def fit(self, train: pd.DataFrame) -> None:
        rows, weights = training_rows(train, self.candidate)
        data = lgb.Dataset(rows[FEATURE_COLUMNS], label=rows[TARGET], weight=weights)
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


def choose_candidate(dataset: Path) -> tuple[Candidate, dict[str, Report]]:
    """ADR 0011: the candidate with the lowest station-averaged MAE on the validation period.

    Also returns every validation report, the baselines' included, for the run and model card.
    """
    models: list[Callable[[], Model]] = [RawBaseline, EpaBaseline]
    models += [partial(LightGbmModel, candidate) for candidate in CANDIDATES.values()]
    raw, epa, *scored = evaluate_validation(dataset, models)
    reports = {"raw": raw, "epa": epa} | dict(zip(CANDIDATES, scored, strict=True))
    best = min(CANDIDATES.values(), key=lambda candidate: reports[candidate.name].headline_mae)
    return best, reports


def train(dataset: Path) -> str:
    """One tracked training run. Returns the MLflow run id."""
    info = json.loads(dataset.with_suffix(".json").read_text())
    candidate, validation = choose_candidate(dataset)
    make_model = partial(LightGbmModel, candidate)
    raw, epa, model = evaluate(dataset, [RawBaseline, EpaBaseline, make_model])
    failures = ship_check(model, raw, epa)

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run() as run:
        mlflow.set_tags(
            {
                "dataset": info["content_hash"],
                "period": "development",
                "ships": not failures,
                "candidate": candidate.name,  # registry.promote rebuilds the model from this
            }
        )
        mlflow.log_params({**PARAMS, "rounds": ROUNDS, "features": ",".join(FEATURE_COLUMNS)})
        mlflow.log_params({"dataset_rows": info["rows"], "dataset_start": info["start"]})
        mlflow.log_params(
            {"window_days": candidate.window_days, "half_life_days": candidate.half_life_days}
        )
        for report in (raw, epa, model):
            mlflow.log_metrics(report_metrics(report))
        for name, report in validation.items():
            mlflow.log_metric(f"validation.{name}.headline_mae", report.headline_mae)
        mlflow.log_dict(
            {
                "reports": [asdict(r) for r in (raw, epa, model)],
                "validation": {name: asdict(r) for name, r in validation.items()},
            },
            "reports.json",
        )
        mlflow.log_text("\n".join(failures) or "passes every ship rule", "ship_check.txt")

        # The model we keep is fitted on all development data, never on the final test period
        development, _ = split_final_test(
            pd.read_parquet(dataset), datetime.fromisoformat(info["final_test_start"])
        )
        final_model = make_model()
        final_model.fit(development)
        logged = mlflow.lightgbm.log_model(
            final_model.booster,
            name="model",
            # Floats in the signature, so a missing weather value at serving time is allowed
            input_example=development[FEATURE_COLUMNS].head(5).astype("float64"),
        )
        mlflow.set_tag("model_uri", logged.model_uri)  # what the registry promotes

    print("Validation period, headline MAE (picks the candidate):")
    for name, report in validation.items():
        print(f"  {name:<16} {report.headline_mae:.2f}")
    print(f"Chosen: {candidate.name}\n")
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
