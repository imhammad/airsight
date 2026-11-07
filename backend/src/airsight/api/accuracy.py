"""Live accuracy: how far the stored corrections were from the official monitors.

Only the champion's own values count, and only hours it never trained on (routes/model.py sets
the window), so this is an out-of-sample score that can be compared with the final test.
"""

from datetime import datetime

from sqlalchemy import Connection, text

from airsight.api.schemas import Accuracy, Errors, StationAccuracy

# Corrected, raw and EPA-corrected values against each sensor's nearest official monitor, the
# same pairing the training dataset uses. EPA = Barkjohn et al. 2021, as in ml/evaluation.py.
ACCURACY_SQL = text("""
    WITH nearest AS (
        SELECT DISTINCT ON (lowcost_sensor_id) lowcost_sensor_id, reference_sensor_id
        FROM sensor_pairs
        ORDER BY lowcost_sensor_id, distance_m
    ),
    hours AS (
        SELECT
            m.name AS station,
            c.sensor_id,
            c.pm25 AS corrected,
            (l.pm25_a + l.pm25_b) / 2 AS raw,
            0.524 * (l.pm25_a + l.pm25_b) / 2 - 0.0862 * l.humidity + 5.75 AS epa,
            r.pm25 AS official
        FROM corrected_readings c
        JOIN nearest n ON n.lowcost_sensor_id = c.sensor_id
        JOIN sensors m ON m.id = n.reference_sensor_id
        JOIN reference_readings r ON r.sensor_id = n.reference_sensor_id AND r.time = c.time
        JOIN lowcost_readings l ON l.sensor_id = c.sensor_id AND l.time = c.time
        WHERE c.time >= :start AND c.time < :end AND c.model_version = :model_version
    )
    SELECT
        station,
        count(DISTINCT sensor_id) AS sensors,
        count(*) AS hours,
        avg(abs(corrected - official)) AS mae_corrected,
        avg(abs(raw - official)) AS mae_raw,
        avg(abs(epa - official)) AS mae_epa,
        avg(corrected - official) AS bias
    FROM hours
    GROUP BY station
    ORDER BY station
""")


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 2) if present else None


def score(connection: Connection, model_version: str, start: datetime, end: datetime) -> Accuracy:
    """How far the stored corrections were from the official monitors in [start, end)."""
    rows = connection.execute(
        ACCURACY_SQL, {"model_version": model_version, "start": start, "end": end}
    ).mappings()
    stations = [
        StationAccuracy(
            station=row["station"],
            sensors=row["sensors"],
            hours=row["hours"],
            mae=Errors(
                corrected=_round(row["mae_corrected"]),
                raw=_round(row["mae_raw"]),
                epa=_round(row["mae_epa"]),
            ),
            bias=_round(row["bias"]),
        )
        for row in rows
    ]
    return Accuracy(
        model_version=model_version,
        start=start,
        end=end,
        hours=sum(s.hours for s in stations),
        headline_mae=Errors(
            corrected=_mean([s.mae.corrected for s in stations]),
            raw=_mean([s.mae.raw for s in stations]),
            epa=_mean([s.mae.epa for s in stations]),
        ),
        stations=stations,
    )
