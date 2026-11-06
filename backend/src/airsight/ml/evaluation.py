"""Score correction models the way ADR 0007 decided: leave one station out.

Every model, including the baselines, goes through the same code: for each official monitor,
fit on the other monitors' sensors and predict this monitor's sensors. The headline number is
the average of the per-station MAEs, so busy stations can't hide bad ones.

Run from backend/:  uv run python -m airsight.ml.evaluation            (development data)
                    uv run python -m airsight.ml.evaluation --final    (once per release)
"""

import argparse
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from airsight.ml.dataset import DATASETS_DIR

# US AQI breakpoints for PM2.5 (µg/m³), applied to the official reading
BANDS = {"good": (0.0, 9.0), "moderate": (9.0, 35.4), "high": (35.4, math.inf)}
# ADR 0007: fewer test hours than this and we make no claim about a band
MIN_BAND_HOURS = 100
REPORTS_DIR = Path("../data/reports")  # git-ignored, like the datasets


class Model(Protocol):
    name: str

    def fit(self, train: pd.DataFrame) -> None: ...

    def predict(self, frame: pd.DataFrame) -> pd.Series: ...


class RawBaseline:
    """The sensor's own reading: the average of its two counters."""

    name = "raw"

    def fit(self, train: pd.DataFrame) -> None:
        pass

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        return frame["raw"].astype(float)


class EpaBaseline:
    """The EPA US-wide PurpleAir correction (Barkjohn et al. 2021)."""

    name = "epa"

    def fit(self, train: pd.DataFrame) -> None:
        pass

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        return 0.524 * frame["raw"] - 0.0862 * frame["sensor_humidity"] + 5.75


@dataclass(frozen=True)
class Metrics:
    hours: int
    mae: float
    bias: float  # mean of predicted − official: positive means the model reads too high
    rmse: float


@dataclass(frozen=True)
class Report:
    model: str
    headline_mae: float  # average of the per-station MAEs
    overall: Metrics
    stations: dict[str, Metrics]
    bands: dict[str, Metrics]


def split_final_test(
    frame: pd.DataFrame, final_test_start: datetime
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Development data, and the final test period that is scored once per release."""
    is_final = frame["time"] >= pd.Timestamp(final_test_start)
    return frame[~is_final], frame[is_final]


def leave_one_station_out(
    make_model: Callable[[], Model], train: pd.DataFrame, test: pd.DataFrame
) -> pd.DataFrame:
    """Predict each station's test rows with a model fitted on the other stations' train rows."""
    parts = []
    for station, station_test in test.groupby("station", sort=True):
        model = make_model()
        model.fit(train[train["station"] != station])
        part = station_test[["station", "sensor_id", "time", "official"]].copy()
        part["predicted"] = model.predict(station_test).to_numpy()
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def metrics(predictions: pd.DataFrame) -> Metrics:
    error = predictions["predicted"] - predictions["official"]
    if error.empty:
        return Metrics(hours=0, mae=math.nan, bias=math.nan, rmse=math.nan)
    return Metrics(
        hours=len(error),
        mae=float(error.abs().mean()),
        bias=float(error.mean()),
        rmse=float(np.sqrt((error**2).mean())),
    )


def score(model: str, predictions: pd.DataFrame) -> Report:
    stations = {
        str(station): metrics(rows) for station, rows in predictions.groupby("station", sort=True)
    }
    bands = {}
    for band, (low, high) in BANDS.items():
        official = predictions["official"]
        # The good band starts at "anything up to 9", so it also keeps readings of exactly 0
        in_band = (official <= high) & ((official > low) | (low == 0.0))
        bands[band] = metrics(predictions[in_band])
    return Report(
        model=model,
        headline_mae=float(np.mean([m.mae for m in stations.values()])),
        overall=metrics(predictions),
        stations=stations,
        bands=bands,
    )


def ship_check(candidate: Report, raw: Report, epa: Report) -> list[str]:
    """The ADR 0007 ship rules. Returns the rules the candidate fails; empty means ship."""
    failures = []
    if candidate.headline_mae >= epa.headline_mae:
        failures.append(
            f"headline MAE {candidate.headline_mae:.2f} is not below EPA's {epa.headline_mae:.2f}"
        )
    moderate = candidate.bands["moderate"]
    if moderate.hours < MIN_BAND_HOURS:
        failures.append(f"only {moderate.hours} moderate hours: too few to check rule 2")
    elif moderate.mae > raw.bands["moderate"].mae:
        failures.append(
            f"moderate MAE {moderate.mae:.2f} is above raw's {raw.bands['moderate'].mae:.2f}"
        )
    wins = sum(candidate.stations[s].mae < epa.stations[s].mae for s in candidate.stations)
    if wins * 2 <= len(candidate.stations):
        failures.append(f"beats EPA at only {wins} of {len(candidate.stations)} stations")
    return failures


def format_report(report: Report) -> str:
    """A plain-text table for the terminal and for pasting into docs."""

    def row(name: str, m: Metrics) -> str:
        if m.hours < MIN_BAND_HOURS and name in BANDS:
            return f"  {name:<32} {m.hours:>7}   (too few hours to claim)"
        return f"  {name:<32} {m.hours:>7} {m.mae:>6.2f} {m.bias:>+6.2f} {m.rmse:>6.2f}"

    lines = [
        f"{report.model}: headline MAE {report.headline_mae:.2f} µg/m³ (mean of stations)",
        f"  {'':<32} {'hours':>7} {'MAE':>6} {'bias':>6} {'RMSE':>6}",
        row("all hours", report.overall),
        *(row(station, m) for station, m in report.stations.items()),
        *(row(band, m) for band, m in report.bands.items()),
    ]
    return "\n".join(lines)


BASELINES: list[Callable[[], Model]] = [RawBaseline, EpaBaseline]


def latest_dataset(directory: Path = DATASETS_DIR) -> Path:
    files = sorted(directory.glob("pairs-*.parquet"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise SystemExit("No dataset found. Build one: uv run python -m airsight.ml.dataset")
    return files[-1]


def evaluate(dataset: Path, models: list[Callable[[], Model]], final: bool = False) -> list[Report]:
    """Score every model on one dataset: development data, or the final test period."""
    info = json.loads(dataset.with_suffix(".json").read_text())
    frame = pd.read_parquet(dataset)
    development, final_test = split_final_test(
        frame, datetime.fromisoformat(info["final_test_start"])
    )
    test = final_test if final else development
    reports = []
    for make_model in models:
        predictions = leave_one_station_out(make_model, development, test)
        reports.append(score(make_model().name, predictions))
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, help="Parquet file (default: the newest one)")
    parser.add_argument(
        "--final", action="store_true", help="score the final test period (once per release)"
    )
    args = parser.parse_args()
    dataset: Path = args.dataset or latest_dataset()
    period = "final" if args.final else "development"

    reports = evaluate(dataset, BASELINES, final=args.final)

    print(f"Dataset {dataset.name}, {period} period, leave one station out\n")
    for report in reports:
        print(format_report(report), end="\n\n")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"{dataset.stem}-{period}.json"
    out.write_text(json.dumps([asdict(r) for r in reports], indent=2) + "\n")
    print(f"Written to {out}")


if __name__ == "__main__":
    main()
