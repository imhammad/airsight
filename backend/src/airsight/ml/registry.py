"""Promote a trained model to champion, but only if it passes the final test.

A training run (ml/train.py) is scored on development data only. Promotion is the release gate
from ADR 0007: retrain leaving one station out, score the final 14 days once, apply the ship
rules, and only then register the run's model and point the "champion" alias at it. Serving
always loads the champion, never "the latest run".

When there already is a champion, ADR 0011 adds two rules: the final test must be 14 days the
champion was never trained or tested on, and the new model must beat the champion on them.

Run from backend/ with the stack up:  uv run python -m airsight.ml.registry promote <run_id>
"""

import argparse
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

import lightgbm as lgb
import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INVALID_PARAMETER_VALUE, RESOURCE_DOES_NOT_EXIST, ErrorCode

from airsight.core.cache import clear_model_cache
from airsight.core.config import get_settings
from airsight.core.logging import configure_logging
from airsight.ml.dataset import DATASETS_DIR, FINAL_TEST_DAYS
from airsight.ml.evaluation import (
    EpaBaseline,
    RawBaseline,
    Report,
    evaluate,
    format_report,
    score,
    ship_check,
    split_final_test,
)
from airsight.ml.features import INPUT_COLUMNS
from airsight.ml.predict import correct
from airsight.ml.train import ALL_DATA, CANDIDATES, LightGbmModel, report_metrics

logger = logging.getLogger(__name__)

MODEL_NAME = "airsight-correction"
CHAMPION = "champion"
# What MLflow answers when nothing has been promoted yet
NOT_PROMOTED = {ErrorCode.Name(RESOURCE_DOES_NOT_EXIST), ErrorCode.Name(INVALID_PARAMETER_VALUE)}


class PromotionRefusedError(Exception):
    """The model failed a ship rule on the final test, so it was not registered."""


def current_champion() -> tuple[lgb.Booster, datetime | None] | None:
    """The champion and the start of its final test (trained_before), or None if there is none."""
    client = MlflowClient()
    try:
        version = client.get_model_version_by_alias(MODEL_NAME, CHAMPION)
    except MlflowException as error:
        if error.error_code in NOT_PROMOTED:
            return None
        raise
    booster: lgb.Booster = mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}/{version.version}")
    trained_before = version.tags.get("trained_before")
    return booster, datetime.fromisoformat(trained_before) if trained_before else None


def score_stored_model(booster: lgb.Booster, name: str, final_test: pd.DataFrame) -> Report:
    """A stored model's answers on the final test, computed the way serving computes them."""
    predictions = final_test[["station", "sensor_id", "time", "official"]].copy()
    predictions["predicted"] = correct(booster, final_test[INPUT_COLUMNS]).to_numpy()
    return score(name, predictions)


def against_champion(run_model_uri: str, dataset: Path) -> tuple[list[str], list[Report]]:
    """ADR 0011: failed rules and both scores, when the new model would replace a champion."""
    champion = current_champion()
    if champion is None:
        return [], []  # the first model only has to pass the ship rules
    booster, trained_before = champion
    info = json.loads(dataset.with_suffix(".json").read_text())
    final_test_start = datetime.fromisoformat(info["final_test_start"])
    if trained_before is None:
        return ["the champion has no trained_before tag, so the final test can't be checked"], []
    fresh_from = trained_before + timedelta(days=FINAL_TEST_DAYS)
    if final_test_start < fresh_from:
        return [
            f"the final test starts {final_test_start:%Y-%m-%d}, but the champion trained or "
            f"was tested on hours until {fresh_from:%Y-%m-%d}; build a dataset that ends "
            f"{fresh_from + timedelta(days=FINAL_TEST_DAYS):%Y-%m-%d} or later"
        ], []
    _, final_test = split_final_test(pd.read_parquet(dataset), final_test_start)
    new = score_stored_model(mlflow.lightgbm.load_model(run_model_uri), "candidate", final_test)
    old = score_stored_model(booster, "champion", final_test)
    if new.headline_mae >= old.headline_mae:
        return [
            f"final-test MAE {new.headline_mae:.2f} is not below the champion's "
            f"{old.headline_mae:.2f}"
        ], [new, old]
    return [], [new, old]


def promote(run_id: str, datasets_dir: Path = DATASETS_DIR) -> int:
    """Score the run's model setup on the final test; register it as champion if it ships."""
    client = MlflowClient()
    run = client.get_run(run_id)
    if "model_uri" not in run.data.tags:  # runs from before this module existed
        raise PromotionRefusedError("run has no model_uri tag; train a new run with ml.train")
    dataset = datasets_dir / f"pairs-{run.data.tags['dataset']}.parquet"
    candidate = CANDIDATES[run.data.tags.get("candidate", ALL_DATA.name)]

    make_model = partial(LightGbmModel, candidate)
    raw, epa, model = evaluate(dataset, [RawBaseline, EpaBaseline, make_model], final=True)
    failures = ship_check(model, raw, epa)
    champion_failures, head_to_head = against_champion(run.data.tags["model_uri"], dataset)
    failures += champion_failures

    # Record the final-test verdict on the run itself, pass or fail
    reports = [raw, epa, model, *head_to_head]
    with mlflow.start_run(run_id=run_id):
        for report in reports:
            mlflow.log_metrics({f"final.{k}": v for k, v in report_metrics(report).items()})
        mlflow.log_dict({"reports": [asdict(r) for r in reports]}, "final_reports.json")
        mlflow.set_tag("final_ships", not failures)
    for report in reports:
        print(format_report(report), end="\n\n")
    if failures:
        raise PromotionRefusedError("; ".join(failures))

    version = mlflow.register_model(run.data.tags["model_uri"], MODEL_NAME)
    client.set_model_version_tag(MODEL_NAME, version.version, "dataset", run.data.tags["dataset"])
    # The model never saw hours from here on, so live accuracy counts only those (GET /v1/accuracy)
    trained_before = json.loads(dataset.with_suffix(".json").read_text())["final_test_start"]
    client.set_model_version_tag(MODEL_NAME, version.version, "trained_before", trained_before)
    client.set_registered_model_alias(MODEL_NAME, CHAMPION, version.version)
    clear_model_cache(get_settings().redis_url)  # so /v1/model shows the new champion now
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
