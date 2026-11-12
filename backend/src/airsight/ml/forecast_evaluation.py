"""Score air quality forecasts the way ADR 0012 decided: a rolling-origin backtest.

The development period ends with four 7-day folds. Each fold's model learns only from rows whose
target hour came before the fold started, then forecasts every issue hour inside it, the way the
live job will. Scores are averaged per monitor first, like the correction's headline (ADR 0007).

Run from backend/:  uv run python -m airsight.ml.forecast_evaluation            (backtest)
                    uv run python -m airsight.ml.forecast_evaluation --final    (once per release)
"""

import argparse
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from airsight.ml.dataset import DATASETS_DIR
from airsight.ml.evaluation import REPORTS_DIR
from airsight.ml.forecast_features import TARGET

FOLDS = 4
FOLD_DAYS = 7
QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
HORIZON_GROUPS = {"1-6h": (1, 6), "7-12h": (7, 12), "13-24h": (13, 24)}
# ADR 0012 rule 3: the p10 to p90 range must hold between 75% and 85% of hours
COVERAGE_RANGE = (0.75, 0.85)


class ForecastModel(Protocol):
    name: str
    has_range: bool  # False for point forecasts, whose p10 and p90 are just the p50

    def fit(self, train: pd.DataFrame) -> None: ...

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Columns p10, p50 and p90, on the frame's index."""
        ...


class _PointForecast:
    has_range = False
    column: str

    def fit(self, train: pd.DataFrame) -> None:
        pass

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        value = frame[self.column].astype(float)
        return pd.DataFrame({name: value for name in QUANTILES}, index=frame.index)


class Persistence(_PointForecast):
    """The monitor's latest reading, for every hour ahead."""

    name = "persistence"
    column = "official_now"


class SameHourYesterday(_PointForecast):
    """The monitor's reading 24 hours before the target hour."""

    name = "same_hour_yesterday"
    column = "official_day_before"


@dataclass(frozen=True)
class ForecastReport:
    model: str
    rows: int
    headline_mae: float  # MAE of p50, averaged over stations
    groups: dict[str, float]  # the same, by hours ahead
    stations: dict[str, float]
    coverage: float | None  # share of hours inside p10 to p90, averaged over stations
    pinball: float  # mean quantile loss over p10, p50 and p90, averaged over stations


def _station_mean(values: pd.Series, stations: pd.Series) -> float:
    return float(values.groupby(stations).mean().mean()) if len(values) else math.nan


def pinball_loss(official: pd.Series, predicted: pd.Series, quantile: float) -> pd.Series:
    """The loss a quantile forecast is trained on: under-forecasts cost `quantile` per unit."""
    error = official - predicted
    return pd.Series(np.maximum(quantile * error, (quantile - 1) * error), index=official.index)


def score(model: str, has_range: bool, predictions: pd.DataFrame) -> ForecastReport:
    """predictions: station, horizon, official, p10, p50, p90."""
    stations = predictions["station"]
    error = (predictions["p50"] - predictions[TARGET]).abs()
    groups = {}
    for name, (low, high) in HORIZON_GROUPS.items():
        in_group = predictions["horizon"].between(low, high)
        groups[name] = _station_mean(error[in_group], stations[in_group])
    inside = predictions[TARGET].between(predictions["p10"], predictions["p90"])
    loss = sum(
        pinball_loss(predictions[TARGET], predictions[column], q) for column, q in QUANTILES.items()
    ) / len(QUANTILES)
    return ForecastReport(
        model=model,
        rows=len(predictions),
        headline_mae=_station_mean(error, stations),
        groups=groups,
        stations={str(s): float(e) for s, e in error.groupby(stations).mean().items()},
        coverage=_station_mean(inside.astype(float), stations) if has_range else None,
        pinball=_station_mean(pd.Series(loss, index=predictions.index), stations),
    )


def split_final_test(
    frame: pd.DataFrame, final_test_start: datetime
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Development rows, and the final test rows (issued from final_test_start on).

    Development keeps only rows whose target hour is before the final test, so no label from
    the final test period is ever learned. Rows issued just before it with a target inside it
    belong to neither.
    """
    start = pd.Timestamp(final_test_start)
    return frame[frame["target_time"] < start], frame[frame["issue_time"] >= start]


def fold_starts(final_test_start: datetime) -> list[datetime]:
    """The first hour of each backtest fold, oldest first."""
    return [final_test_start - timedelta(days=FOLD_DAYS * (FOLDS - fold)) for fold in range(FOLDS)]


def _predict(
    make_model: Callable[[], ForecastModel], train: pd.DataFrame, test: pd.DataFrame
) -> tuple[pd.DataFrame, ForecastModel]:
    """Fit a fresh model on train and forecast test, with the quantiles in order."""
    model = make_model()
    model.fit(train)
    part = test[["station", "sensor_id", "issue_time", "horizon", TARGET]].copy()
    predicted = model.predict(test)
    # Quantile models can cross; sorting keeps p10 <= p50 <= p90
    ordered = np.sort(predicted[list(QUANTILES)].to_numpy(), axis=1)
    part[list(QUANTILES)] = ordered
    return part, model


def backtest(
    make_model: Callable[[], ForecastModel], development: pd.DataFrame, final_test_start: datetime
) -> ForecastReport:
    """Rolling-origin backtest on the last four weeks of the development period."""
    parts = []
    has_range = False
    for start in fold_starts(final_test_start):
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(start + timedelta(days=FOLD_DAYS))
        train = development[development["target_time"] < start_ts]
        test = development[development["issue_time"].between(start_ts, end_ts, inclusive="left")]
        part, model = _predict(make_model, train, test)
        has_range = model.has_range
        parts.append(part)
    name = make_model().name
    return score(name, has_range, pd.concat(parts, ignore_index=True))


def evaluate_final(
    make_model: Callable[[], ForecastModel], development: pd.DataFrame, final_test: pd.DataFrame
) -> ForecastReport:
    """Fit on all development rows, then score the final test period once."""
    predictions, model = _predict(make_model, development, final_test)
    return score(model.name, model.has_range, predictions)


def ship_check(
    candidate: ForecastReport, persistence: ForecastReport, yesterday: ForecastReport
) -> list[str]:
    """The ADR 0012 ship rules. Returns the rules the candidate fails; empty means ship."""
    failures = []
    best_baseline = min(persistence.headline_mae, yesterday.headline_mae)
    if candidate.headline_mae >= best_baseline:
        failures.append(
            f"MAE {candidate.headline_mae:.2f} is not below the best baseline's {best_baseline:.2f}"
        )
    wins = sum(
        candidate.groups[group] < min(persistence.groups[group], yesterday.groups[group])
        for group in HORIZON_GROUPS
    )
    if wins < 2:
        failures.append(f"beats the better baseline in only {wins} of 3 horizon groups")
    low, high = COVERAGE_RANGE
    if candidate.coverage is None:
        failures.append("gives no p10 to p90 range")
    elif not low <= candidate.coverage <= high:
        failures.append(f"p10 to p90 range holds {candidate.coverage:.0%} of hours, not 75% to 85%")
    return failures


def format_report(report: ForecastReport) -> str:
    coverage = "n/a" if report.coverage is None else f"{report.coverage:.0%}"
    groups = "  ".join(f"{name} {mae:.2f}" for name, mae in report.groups.items())
    return (
        f"{report.model}: MAE {report.headline_mae:.2f} µg/m³ (mean of stations), "
        f"by hours ahead: {groups}; coverage {coverage}; pinball {report.pinball:.2f}"
    )


BASELINES: list[Callable[[], ForecastModel]] = [Persistence, SameHourYesterday]


def latest_forecast_dataset(directory: Path = DATASETS_DIR) -> Path:
    files = sorted(directory.glob("forecast-*.parquet"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise SystemExit(
            "No dataset found. Build one: uv run python -m airsight.ml.forecast_dataset"
        )
    return files[-1]


def evaluate(
    dataset: Path, models: list[Callable[[], ForecastModel]], final: bool = False
) -> list[ForecastReport]:
    """Backtest every model on one dataset, or score the final test period."""
    info = json.loads(dataset.with_suffix(".json").read_text())
    final_test_start = datetime.fromisoformat(info["final_test_start"])
    development, final_test = split_final_test(pd.read_parquet(dataset), final_test_start)
    if final:
        return [evaluate_final(make, development, final_test) for make in models]
    return [backtest(make, development, final_test_start) for make in models]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, help="Parquet file (default: the newest one)")
    parser.add_argument(
        "--final", action="store_true", help="score the final test period (once per release)"
    )
    args = parser.parse_args()
    dataset: Path = args.dataset or latest_forecast_dataset()
    period = "final" if args.final else "backtest"

    reports = evaluate(dataset, BASELINES, final=args.final)

    print(f"Dataset {dataset.name}, {period}\n")
    for report in reports:
        print(format_report(report))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"{dataset.stem}-{period}.json"
    out.write_text(json.dumps([asdict(r) for r in reports], indent=2) + "\n")
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
