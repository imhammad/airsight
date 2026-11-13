"""Live forecast accuracy: how far the stored forecasts were from what the monitors then read.

Every forecast is issued before its target hour, so every scored hour is out of sample. Scores
follow ADR 0012: the p50 against two baselines on the same hours, and how often the p10 to p90
range held the real value, averaged per station first so busy monitors can't hide weak ones.
"""

from datetime import datetime

from sqlalchemy import Connection, RowMapping, text

from airsight.api.schemas import (
    ForecastAccuracy,
    ForecastErrors,
    HorizonAccuracy,
    StationForecastAccuracy,
)

HORIZON_GROUPS = ("1-6", "7-12", "13-24")

# Each forecast hour against the sensor's nearest monitor at the target hour. Persistence is the
# monitor at the issue hour and same hour yesterday the monitor 24 hours before the target, as in
# ml/forecast_evaluation.py. Only hours where both baselines exist count, so all three are scored
# on exactly the same hours. Only the newest model version counts.
SCORE_SQL = text("""
    WITH nearest AS (
        SELECT DISTINCT ON (lowcost_sensor_id) lowcost_sensor_id, reference_sensor_id
        FROM sensor_pairs
        ORDER BY lowcost_sensor_id, distance_m
    ),
    newest AS (
        SELECT model_version FROM forecasts
        WHERE target_time >= :start AND target_time < :end
        ORDER BY issue_time DESC
        LIMIT 1
    ),
    scored AS (
        SELECT
            m.name AS station,
            f.sensor_id,
            CASE
                WHEN f.horizon <= 6 THEN '1-6'
                WHEN f.horizon <= 12 THEN '7-12'
                ELSE '13-24'
            END AS horizons,
            f.p10,
            f.p50,
            f.p90,
            r.pm25 AS official,
            at_issue.pm25 AS persistence,
            yesterday.pm25 AS same_hour_yesterday
        FROM forecasts f
        JOIN newest ON newest.model_version = f.model_version
        JOIN nearest n ON n.lowcost_sensor_id = f.sensor_id
        JOIN sensors m ON m.id = n.reference_sensor_id
        JOIN reference_readings r
            ON r.sensor_id = n.reference_sensor_id AND r.time = f.target_time
        JOIN reference_readings at_issue
            ON at_issue.sensor_id = n.reference_sensor_id AND at_issue.time = f.issue_time
        JOIN reference_readings yesterday
            ON yesterday.sensor_id = n.reference_sensor_id
            AND yesterday.time = f.target_time - interval '24 hours'
        WHERE f.target_time >= :start AND f.target_time < :end
    )
    SELECT
        station,
        horizons,
        count(DISTINCT sensor_id) AS sensors,
        count(*) AS hours,
        avg(abs(p50 - official)) AS mae_forecast,
        avg(abs(persistence - official)) AS mae_persistence,
        avg(abs(same_hour_yesterday - official)) AS mae_same_hour_yesterday,
        avg((official BETWEEN p10 AND p90)::int) AS coverage,
        (SELECT model_version FROM newest) AS model_version
    FROM scored
    GROUP BY GROUPING SETS ((station), (station, horizons))
    ORDER BY station, horizons NULLS FIRST
""")


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 2) if present else None


def _errors(row: RowMapping) -> ForecastErrors:
    return ForecastErrors(
        forecast=_round(row["mae_forecast"]),
        persistence=_round(row["mae_persistence"]),
        same_hour_yesterday=_round(row["mae_same_hour_yesterday"]),
    )


def _headline(errors: list[ForecastErrors]) -> ForecastErrors:
    return ForecastErrors(
        forecast=_mean([e.forecast for e in errors]),
        persistence=_mean([e.persistence for e in errors]),
        same_hour_yesterday=_mean([e.same_hour_yesterday for e in errors]),
    )


def score(connection: Connection, start: datetime, end: datetime) -> ForecastAccuracy:
    """How the newest forecast model did on target hours in [start, end)."""
    rows = list(connection.execute(SCORE_SQL, {"start": start, "end": end}).mappings())
    overall = [row for row in rows if row["horizons"] is None]
    stations = [
        StationForecastAccuracy(
            station=row["station"],
            sensors=row["sensors"],
            hours=row["hours"],
            mae=_errors(row),
            coverage=_round(row["coverage"]),
        )
        for row in overall
    ]
    by_horizon = []
    for group in HORIZON_GROUPS:
        group_rows = [row for row in rows if row["horizons"] == group]
        by_horizon.append(
            HorizonAccuracy(
                hours_ahead=group,
                hours=sum(row["hours"] for row in group_rows),
                mae=_headline([_errors(row) for row in group_rows]),
                coverage=_mean([_round(row["coverage"]) for row in group_rows]),
            )
        )
    return ForecastAccuracy(
        model_version=rows[0]["model_version"] if rows else None,
        start=start,
        end=end,
        hours=sum(s.hours for s in stations),
        headline_mae=_headline([s.mae for s in stations]),
        coverage=_mean([s.coverage for s in stations]),
        by_horizon=by_horizon,
        stations=stations,
    )
