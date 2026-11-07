"""Promote a trained model to champion, but only if it passes the final test.

A training run (ml/train.py) is scored on development data only. Promotion is the release gate
from ADR 0007: retrain leaving one station out, score the final 14 days once, apply the ship
rules, and only then register the run's model and point the "champion" alias at it. Serving
always loads the champion, never "the latest run".

Run from backend/ with the stack up:  uv run python -m airsight.ml.registry promote <run_id>
"""

import argparse
import logging
from dataclasses import asdict
from pathlib import Path

import lightgbm as lgb
import mlflow
from mlflow import MlflowClient

from airsight.core.config import get_settings
from airsight.core.logging import configure_logging
from airsight.ml.dataset import DATASETS_DIR
from airsight.ml.evaluation import EpaBaseline, RawBaseline, evaluate, format_report, ship_check
from airsight.ml.train import LightGbmModel, report_metrics

logger = logging.getLogger(__name__)

MODEL_NAME = "airsight-correction"
CHAMPION = "champion"


class PromotionRefusedError(Exception):
    """The model failed a ship rule on the final test, so it was not registered."""


def promote(run_id: str, datasets_dir: Path = DATASETS_DIR) -> int:
    """Score the run's model setup on the final test; register it as champion if it ships."""
    client = MlflowClient()
    run = client.get_run(run_id)
    if "model_uri" not in run.data.tags:  # runs from before this module existed
        raise PromotionRefusedError("run has no model_uri tag; train a new run with ml.train")
    dataset = datasets_dir / f"pairs-{run.data.tags['dataset']}.parquet"

    raw, epa, model = evaluate(dataset, [RawBaseline, EpaBaseline, LightGbmModel], final=True)
    failures = ship_check(model, raw, epa)

    # Record the final-test verdict on the run itself, pass or fail
    with mlflow.start_run(run_id=run_id):
        for report in (raw, epa, model):
            mlflow.log_metrics({f"final.{k}": v for k, v in report_metrics(report).items()})
        mlflow.log_dict({"reports": [asdict(r) for r in (raw, epa, model)]}, "final_reports.json")
        mlflow.set_tag("final_ships", not failures)
    for report in (raw, epa, model):
        print(format_report(report), end="\n\n")
    if failures:
        raise PromotionRefusedError("; ".join(failures))

    version = mlflow.register_model(run.data.tags["model_uri"], MODEL_NAME)
    client.set_model_version_tag(MODEL_NAME, version.version, "dataset", run.data.tags["dataset"])
    client.set_registered_model_alias(MODEL_NAME, CHAMPION, version.version)
    return int(version.version)


def load_champion() -> lgb.Booster:
    """The model serving uses. Fails loudly if no model has been promoted yet."""
    booster: lgb.Booster = mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}@{CHAMPION}")
    return booster


def load_champion_version() -> tuple[lgb.Booster, str]:
    """The champion and its name for provenance, such as airsight-correction/1.

    The alias is resolved once and that exact version is loaded, so the name can never belong to
    a different model than the one returned, even if a promotion happens in between.
    """
    version = MlflowClient().get_model_version_by_alias(MODEL_NAME, CHAMPION).version
    booster: lgb.Booster = mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}/{version}")
    return booster, f"{MODEL_NAME}/{version}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    promote_command = commands.add_parser("promote", help="final test, then register if it ships")
    promote_command.add_argument("run_id", help="the MLflow run id that ml.train printed")
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
