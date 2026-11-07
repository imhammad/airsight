from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from airsight.api import accuracy
from airsight.api.deps import Champion, DbConnection, Now
from airsight.api.schemas import Accuracy, ModelInfo

router = APIRouter(tags=["model"])


@router.get("/model", response_model=ModelInfo)
def get_model(champion: Champion) -> ModelInfo:
    """The model behind every corrected value, and how it scored on the final test."""
    return champion


@router.get("/accuracy", response_model=Accuracy)
def get_accuracy(
    connection: DbConnection,
    now: Now,
    champion: Champion,
    days: Annotated[int, Query(ge=1, le=30, description="How many recent days to score")] = 7,
) -> Accuracy:
    """Live error of the champion's corrections against the official monitors.

    Only hours the model never trained on count, so this is an honest out-of-sample number.
    """
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    if champion.trained_before is not None:
        start = min(max(start, champion.trained_before), end)
    return accuracy.score(connection, champion.model_version, start, end)
