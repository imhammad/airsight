"""Promote a forecast run to champion, but only if it passes the final test (ADR 0012).

A training run (ml/forecast_train.py) is scored on the backtest only. Promotion scores the run's
stored model, exactly as serving will load it, on the final 14 days once, applies the ship rules
against both baselines, and only then registers it as airsight-forecast and points the
"champion" alias at it.

Run from backend/ with the stack up:
    uv run python -m airsight.ml.forecast_registry promote <run_id>
"""

import argparse
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from mlflow.pyfunc import PyFuncModel

from airsight.core.config import get_settings
from airsight.core.logging import configure_logging
from airsight.ml.dataset import DATASETS_DIR
from airsight.ml.forecast_evaluation import (
    BASELINES,
    QUANTILES,
    ForecastReport,
    evaluate_final,
    format_report,
    score,
    ship_check,
    split_final_test,
)
from airsight.ml.forecast_features import TARGET
from airsight.ml.forecast_train import QuantileLightGbm, bundle_input, report_metrics
from airsight.ml.registry import CHAMPION, NOT_PROMOTED, PromotionRefusedError

logger = logging.getLogger(__name__)

MODEL_NAME = "airsight-forecast"


def champion_version(client: MlflowClient) -> str | None:
    """The champion's version number, or None if no forecast has been promoted yet."""
    try:
        return str(client.get_model_version_by_alias(MODEL_NAME, CHAMPION).version)
    except MlflowException as error:
        if error.error_code in NOT_PROMOTED:
            return None
        raise


def score_stored_model(model_uri: str, final_test: pd.DataFrame) -> ForecastReport:
    """The stored model's forecasts for the final test, made the way serving will make them."""
    predictions = final_test[["station", "sensor_id", "issue_time", "horizon", TARGET]].copy()
    predicted = pd.DataFrame(mlflow.pyfunc.load_model(model_uri).predict(bundle_input(final_test)))
    predictions[list(QUANTILES)] = predicted[list(QUANTILES)].to_numpy()
    return score(QuantileLightGbm.name, QuantileLightGbm.has_range, predictions)


def promote(run_id: str, datasets_dir: Path = DATASETS_DIR) -> int:
    """Score the run's model on the final test; register it as champion if it ships."""
    client = MlflowClient()
    run = client.get_run(run_id)
    if "model_uri" not in run.data.tags:  # runs from before the model was stored as one bundle
        raise PromotionRefusedError("run has no model_uri tag; train a new run")
    if champion_version(client) is not None:
        # Replacing a champion needs the ADR 0011 head-to-head on fresh days, built with the
        # forecast's first retrain. Until then, refuse rather than replace it unchecked.
        raise PromotionRefusedError("a forecast champion exists; replacing it isn't built yet")

    dataset = datasets_dir / f"forecast-{run.data.tags['dataset']}.parquet"
    info = json.loads(dataset.with_suffix(".json").read_text())
    development, final_test = split_final_test(
        pd.read_parquet(dataset), datetime.fromisoformat(info["final_test_start"])
    )
    persistence, yesterday = (evaluate_final(make, development, final_test) for make in BASELINES)
    model = score_stored_model(run.data.tags["model_uri"], final_test)
    failures = ship_check(model, persistence, yesterday)

    # Record the final-test verdict on the run itself, pass or fail
    reports = [persistence, yesterday, model]
    with mlflow.start_run(run_id=run_id):
        for report in reports:
            mlflow.log_metrics({f"final.{k}": v for k, v in report_metrics(report).items()})
        mlflow.log_dict({"reports": [asdict(r) for r in reports]}, "final_reports.json")
        mlflow.set_tag("final_ships", not failures)
    for report in reports:
        print(format_report(report))
    if failures:
        raise PromotionRefusedError("; ".join(failures))

    version = mlflow.register_model(run.data.tags["model_uri"], MODEL_NAME)
    client.set_model_version_tag(MODEL_NAME, version.version, "dataset", run.data.tags["dataset"])
    # The model never learned from targets from here on, so live scores count only those
    client.set_model_version_tag(
        MODEL_NAME, version.version, "trained_before", info["final_test_start"]
    )
    client.set_registered_model_alias(MODEL_NAME, CHAMPION, version.version)
    return int(version.version)


def load_champion_version() -> tuple[PyFuncModel, str]:
    """The champion and its name for provenance, such as airsight-forecast/1.

    The alias is resolved once and that exact version is loaded, so the name can never belong to
    a different model than the one returned, even if a promotion happens in between.
    """
    version = MlflowClient().get_model_version_by_alias(MODEL_NAME, CHAMPION).version
    return mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}/{version}"), f"{MODEL_NAME}/{version}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    promote_command = commands.add_parser("promote", help="final test, then register if it ships")
    promote_command.add_argument("run_id", help="the MLflow run id that ml.forecast_train printed")
    args = parser.parse_args()
    configure_logging()
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)

    try:
        version = promote(args.run_id)
    except PromotionRefusedError as refused:
        raise SystemExit(f"Not promoted. Final test failed: {refused}") from None
    logger.info("Promoted %s version %d to @%s", MODEL_NAME, version, CHAMPION)


if __name__ == "__main__":
    main()
