"""Daily input drift check (ADR 0013): do the model's live inputs still look like its training data?

For each input, it compares the champion's training period with the last 7 days: the
Wasserstein distance between the two, divided by the training period's standard deviation, so
every input is on the same scale. Above 0.1, the input has drifted. This is Evidently's default
test for numeric columns; we compute it with scipy because Evidently doesn't support pandas 3
(engineering log, 2026-11-21).

The scores go to the database for the exporter and the Model dashboard, and a readable report
goes to MLflow. Drift is a warning for a person to read. It never starts a retrain (ADR 0011).

Run it by hand from backend/ with the stack up:  uv run python -m airsight.observability.drift
"""

import html
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import mlflow
import pandas as pd
from scipy.stats import wasserstein_distance
from sqlalchemy import Engine, text

from airsight.api.champion import load_champion_info
from airsight.core.config import get_settings
from airsight.core.db import get_engine
from airsight.core.logging import configure_logging
from airsight.core.tables import input_drift
from airsight.ml.batch import INPUTS_SQL
from airsight.ml.features import FEATURE_COLUMNS, add_features

logger = logging.getLogger(__name__)

THRESHOLD = 0.1
CURRENT_DAYS = 7
MIN_CURRENT_ROWS = 100
# Evidently's floor for the standard deviation, so an input that never varied can't divide by 0
MIN_SPREAD = 0.001
# Time of day and day of week are spread evenly over any whole week, so they can't drift
DRIFT_FEATURES = [c for c in FEATURE_COLUMNS if c not in ("local_hour", "day_of_week")]
EXPERIMENT = "input-drift"

FIRST_READING_SQL = text("SELECT min(time) FROM lowcost_readings")


class NotEnoughLiveDataError(Exception):
    """Too few clean sensor-hours in the last 7 days to say anything about drift."""


@dataclass(frozen=True)
class FeatureDrift:
    feature: str
    score: float | None  # None when one side has no values for this input
    drifted: bool
    reference_median: float | None
    current_median: float | None


@dataclass(frozen=True)
class DriftReport:
    model_version: str
    checked_at: datetime
    reference_start: datetime
    reference_end: datetime
    current_start: datetime
    current_end: datetime
    reference_rows: int
    current_rows: int
    features: list[FeatureDrift]

    @property
    def drifted(self) -> list[str]:
        return [f.feature for f in self.features if f.drifted]

    @property
    def share_drifted(self) -> float:
        return len(self.drifted) / len(self.features)


def drift_score(reference: pd.Series, current: pd.Series) -> float | None:
    """Wasserstein distance between the two, in units of the reference's standard deviation."""
    reference, current = reference.dropna(), current.dropna()
    if reference.empty or current.empty:
        return None
    spread = max(float(reference.std(ddof=0)), MIN_SPREAD)
    return float(wasserstein_distance(reference, current)) / spread


def _median(values: pd.Series) -> float | None:
    median = values.median()
    return None if pd.isna(median) else float(median)


def compare(reference: pd.DataFrame, current: pd.DataFrame) -> list[FeatureDrift]:
    """Score every input the model uses, except the time features."""
    results = []
    for feature in DRIFT_FEATURES:
        score = drift_score(reference[feature], current[feature])
        results.append(
            FeatureDrift(
                feature=feature,
                score=score,
                drifted=score is not None and score > THRESHOLD,
                reference_median=_median(reference[feature]),
                current_median=_median(current[feature]),
            )
        )
    return results


def load_inputs(engine: Engine, start: datetime, end: datetime) -> pd.DataFrame:
    """The inputs the model sees in serving (ml/batch.py), for clean hours in [start, end)."""
    with engine.connect() as connection:
        rows = pd.read_sql(INPUTS_SQL, connection, params={"start": start, "end": end})
    return add_features(rows)


def training_start(engine: Engine) -> datetime:
    """The training dataset starts on the first whole day of readings (ml/dataset.py)."""
    with engine.connect() as connection:
        first: datetime = connection.execute(FIRST_READING_SQL).scalar_one()
    return first.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def build_report(
    engine: Engine,
    model_version: str,
    reference_start: datetime,
    reference_end: datetime,
    now: datetime,
) -> DriftReport:
    """Compare the training period [reference_start, reference_end) with the last 7 days."""
    current_end = now.replace(minute=0, second=0, microsecond=0)
    current_start = current_end - timedelta(days=CURRENT_DAYS)
    current = load_inputs(engine, current_start, current_end)
    if len(current) < MIN_CURRENT_ROWS:
        raise NotEnoughLiveDataError(
            f"{len(current)} clean sensor-hours since {current_start:%Y-%m-%d %H:%M}"
        )
    reference = load_inputs(engine, reference_start, reference_end)
    return DriftReport(
        model_version=model_version,
        checked_at=now,
        reference_start=reference_start,
        reference_end=reference_end,
        current_start=current_start,
        current_end=current_end,
        reference_rows=len(reference),
        current_rows=len(current),
        features=compare(reference, current),
    )


def store(engine: Engine, report: DriftReport) -> None:
    with engine.begin() as connection:
        connection.execute(
            input_drift.insert(),
            [
                {
                    "checked_at": report.checked_at,
                    "feature": f.feature,
                    "model_version": report.model_version,
                    "score": f.score,
                    "drifted": f.drifted,
                    "reference_median": f.reference_median,
                    "current_median": f.current_median,
                }
                for f in report.features
            ],
        )


def _number(value: float | None) -> str:
    return "n/a" if value is None or math.isnan(value) else f"{value:.2f}"


def render_html(report: DriftReport) -> str:
    """A one-page report a person can open from MLflow."""
    rows = "\n".join(
        f"<tr><td>{html.escape(f.feature)}</td><td>{_number(f.score)}</td>"
        f"<td>{'yes' if f.drifted else 'no'}</td><td>{_number(f.reference_median)}</td>"
        f"<td>{_number(f.current_median)}</td></tr>"
        for f in report.features
    )
    return f"""<!doctype html>
<html lang="en"><head><title>Input drift {report.checked_at:%Y-%m-%d}</title></head>
<body style="font:15px/1.5 system-ui,sans-serif;margin:2rem;color:#1d1f21">
<h1>Input drift, {report.checked_at:%Y-%m-%d}</h1>
<p>{html.escape(report.model_version)}: training period {report.reference_start:%Y-%m-%d} to
{report.reference_end:%Y-%m-%d} ({report.reference_rows:,} sensor-hours) against the last
{CURRENT_DAYS} days, {report.current_start:%Y-%m-%d %H:%M} to {report.current_end:%Y-%m-%d %H:%M}
UTC ({report.current_rows:,} sensor-hours).</p>
<p><strong>{len(report.drifted)} of {len(report.features)} inputs drifted</strong> (score above
{THRESHOLD}). The score is the Wasserstein distance in units of the training period's standard
deviation. Drift is a reason to look, not to retrain (ADR 0011).</p>
<table cellpadding="6"><tr><th>Input</th><th>Score</th><th>Drifted</th><th>Training median</th>
<th>Last {CURRENT_DAYS} days median</th></tr>
{rows}
</table></body></html>
"""


def log_to_mlflow(report: DriftReport) -> str:
    """One run per check in the input-drift experiment. Returns the run id."""
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"drift {report.checked_at:%Y-%m-%d}") as run:
        mlflow.set_tag("model_version", report.model_version)
        mlflow.log_params(
            {
                "reference_start": report.reference_start.isoformat(),
                "reference_end": report.reference_end.isoformat(),
                "current_days": CURRENT_DAYS,
                "threshold": THRESHOLD,
            }
        )
        mlflow.log_metrics(
            {
                "share_drifted": report.share_drifted,
                "reference_rows": report.reference_rows,
                "current_rows": report.current_rows,
            }
        )
        mlflow.log_metrics(
            {f"score.{f.feature}": f.score for f in report.features if f.score is not None}
        )
        mlflow.log_text(render_html(report), "drift_report.html")
    return str(run.info.run_id)


def check_champion(engine: Engine, now: datetime | None = None) -> int:
    """The worker's daily job: score, store and log. Returns the number of inputs scored."""
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    champion = load_champion_info()
    if champion is None or champion.trained_before is None:
        raise RuntimeError("No champion with a trained_before tag to compare against")
    report = build_report(
        engine,
        champion.model_version,
        training_start(engine),
        champion.trained_before,
        now or datetime.now(UTC),
    )
    store(engine, report)
    run_id = log_to_mlflow(report)
    logger.info(
        "Input drift for %s: %d of %d inputs drifted (%s); MLflow run %s",
        report.model_version,
        len(report.drifted),
        len(report.features),
        ", ".join(report.drifted) or "none",
        run_id,
    )
    return len(report.features)


def main() -> None:
    configure_logging()
    check_champion(get_engine())


if __name__ == "__main__":
    main()
