"""What the API says about the champion model, read from the MLflow registry.

The API never loads the model itself (ADR 0005): it only reads the registry's description of
it, so clients can see which model produced the values and how it scored on the final test.
"""

from datetime import UTC, datetime

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from airsight.api.schemas import FinalTest, ModelInfo
from airsight.core.config import get_settings
from airsight.ml.registry import CHAMPION, MODEL_NAME, NOT_PROMOTED

MODEL_CARDS = "https://github.com/imhammad/airsight/blob/main/docs/model-cards"


def _final_test(metrics: dict[str, float]) -> FinalTest | None:
    try:
        return FinalTest(
            headline_mae=round(metrics["final.lightgbm.headline_mae"], 2),
            raw_headline_mae=round(metrics["final.raw.headline_mae"], 2),
            epa_headline_mae=round(metrics["final.epa.headline_mae"], 2),
            hours=int(metrics["final.lightgbm.all.hours"]),
        )
    except KeyError:
        return None


def load_champion_info() -> ModelInfo | None:
    """The current champion, or None if no model has been promoted yet."""
    client = MlflowClient(tracking_uri=get_settings().mlflow_tracking_uri)
    try:
        version = client.get_model_version_by_alias(MODEL_NAME, CHAMPION)
    except MlflowException as error:
        if error.error_code in NOT_PROMOTED:
            return None
        raise
    trained_before = version.tags.get("trained_before")
    metrics = client.get_run(version.run_id).data.metrics if version.run_id else {}
    return ModelInfo(
        name=MODEL_NAME,
        version=int(version.version),
        model_version=f"{MODEL_NAME}/{version.version}",
        dataset=version.tags.get("dataset"),
        trained_before=datetime.fromisoformat(trained_before) if trained_before else None,
        promoted_at=datetime.fromtimestamp(version.creation_timestamp / 1000, UTC),
        final_test=_final_test(metrics),
        model_card=f"{MODEL_CARDS}/{MODEL_NAME}-v{version.version}.md",
    )
