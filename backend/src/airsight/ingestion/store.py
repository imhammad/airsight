"""Write client results into the database. Every write is an upsert, so reruns are safe."""

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, func, select, text
from sqlalchemy.dialects.postgresql import insert

from airsight.core.tables import (
    ingestion_runs,
    lowcost_readings,
    reference_readings,
    sensor_pairs,
    sensors,
    weather,
)
from airsight.ingestion.airnow import ReferenceReading
from airsight.ingestion.open_meteo import WeatherHour
from airsight.ingestion.purpleair import LowcostReading, Sensor
from airsight.ingestion.regions import weather_cell

BATCH_SIZE = 1000


def _batches(rows: Sequence[dict[str, Any]]) -> Iterable[Sequence[dict[str, Any]]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


def _point(latitude: float, longitude: float) -> str:
    # PostGIS writes points as longitude first
    return f"SRID=4326;POINT({longitude} {latitude})"


def _upsert_sensors(connection: Connection, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Insert or update sensors; return the database id for each source_id."""
    ids: dict[str, int] = {}
    for batch in _batches(rows):
        statement = insert(sensors).values(list(batch))
        upsert = statement.on_conflict_do_update(
            index_elements=["source", "source_id"],
            set_={
                "name": statement.excluded.name,
                "location": statement.excluded.location,
                "weather_cell_id": statement.excluded.weather_cell_id,
            },
        )
        returning = upsert.returning(sensors.c.source_id, sensors.c.id)
        ids.update({source_id: id_ for source_id, id_ in connection.execute(returning)})
    return ids


def upsert_reference_stations(
    connection: Connection, readings: Sequence[ReferenceReading]
) -> dict[str, int]:
    stations = {r.station_id: r for r in readings}
    return _upsert_sensors(
        connection,
        [
            {
                "source": "airnow",
                "source_id": r.station_id,
                "kind": "reference",
                "name": r.site_name,
                "location": _point(r.latitude, r.longitude),
                "weather_cell_id": weather_cell(r.latitude, r.longitude),
            }
            for r in stations.values()
        ],
    )


def upsert_lowcost_sensors(connection: Connection, found: Sequence[Sensor]) -> dict[int, int]:
    ids = _upsert_sensors(
        connection,
        [
            {
                "source": "purpleair",
                "source_id": str(s.sensor_index),
                "kind": "lowcost",
                "name": s.name,
                "location": _point(s.latitude, s.longitude),
                "weather_cell_id": weather_cell(s.latitude, s.longitude),
            }
            for s in {s.sensor_index: s for s in found}.values()
        ],
    )
    return {int(source_id): id_ for source_id, id_ in ids.items()}


def upsert_reference_readings(
    connection: Connection, readings: Sequence[ReferenceReading], ids: dict[str, int]
) -> int:
    rows = [
        {"sensor_id": ids[r.station_id], "time": r.time, "pm25": r.pm25}
        for r in readings
        if r.station_id in ids
    ]
    for batch in _batches(rows):
        statement = insert(reference_readings).values(list(batch))
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=["sensor_id", "time"], set_={"pm25": statement.excluded.pm25}
            )
        )
    return len(rows)


def upsert_lowcost_readings(
    connection: Connection, readings: Sequence[LowcostReading], ids: dict[int, int]
) -> int:
    rows = [
        {
            "sensor_id": ids[r.sensor_index],
            "time": r.time,
            "pm25_a": r.pm25_a,
            "pm25_b": r.pm25_b,
            "humidity": r.humidity,
        }
        for r in readings
        if r.sensor_index in ids
    ]
    for batch in _batches(rows):
        statement = insert(lowcost_readings).values(list(batch))
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=["sensor_id", "time"],
                set_={
                    "pm25_a": statement.excluded.pm25_a,
                    "pm25_b": statement.excluded.pm25_b,
                    "humidity": statement.excluded.humidity,
                },
            )
        )
    return len(rows)


def upsert_weather(connection: Connection, cell_id: str, hours: Sequence[WeatherHour]) -> int:
    rows = [
        {
            "cell_id": cell_id,
            "time": h.time,
            "temperature": h.temperature,
            "relative_humidity": h.relative_humidity,
            "wind_speed": h.wind_speed,
            "wind_direction": h.wind_direction,
            "precipitation": h.precipitation,
        }
        for h in hours
    ]
    columns = ["temperature", "relative_humidity", "wind_speed", "wind_direction", "precipitation"]
    for batch in _batches(rows):
        statement = insert(weather).values(list(batch))
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=["cell_id", "time"],
                # A missing new value never erases a value we already have
                set_={c: func.coalesce(statement.excluded[c], weather.c[c]) for c in columns},
            )
        )
    return len(rows)


def refresh_sensor_pairs(connection: Connection, max_distance_m: float) -> int:
    """Rebuild the list of low-cost sensors within max_distance_m of an official monitor."""
    connection.execute(sensor_pairs.delete())
    result = connection.execute(
        text("""
            INSERT INTO sensor_pairs (reference_sensor_id, lowcost_sensor_id, distance_m)
            SELECT r.id, l.id, ST_Distance(r.location, l.location)
            FROM sensors r
            JOIN sensors l ON ST_DWithin(r.location, l.location, :max_distance_m)
            WHERE r.kind = 'reference' AND l.kind = 'lowcost'
        """),
        {"max_distance_m": max_distance_m},
    )
    return result.rowcount


def paired_lowcost_sensors(connection: Connection) -> dict[int, int]:
    """PurpleAir sensor_index -> database id, for every sensor that has a monitor nearby."""
    rows = connection.execute(
        select(sensors.c.source_id, sensors.c.id)
        .where(sensors.c.id.in_(select(sensor_pairs.c.lowcost_sensor_id)))
        .order_by(sensors.c.id)
    )
    return {int(source_id): id_ for source_id, id_ in rows}


def weather_cells_in_use(connection: Connection) -> list[str]:
    """Weather cells of every official monitor and every paired low-cost sensor."""
    rows = connection.execute(
        select(sensors.c.weather_cell_id)
        .where(
            (sensors.c.kind == "reference")
            | sensors.c.id.in_(select(sensor_pairs.c.lowcost_sensor_id))
        )
        .distinct()
        .order_by(sensors.c.weather_cell_id)
    )
    return [cell for (cell,) in rows if cell is not None]


def reference_locations(connection: Connection) -> list[tuple[float, float]]:
    """(latitude, longitude) of every official monitor."""
    rows = connection.execute(
        text("""
            SELECT ST_Y(location::geometry), ST_X(location::geometry)
            FROM sensors WHERE kind = 'reference' ORDER BY id
        """)
    )
    return [(latitude, longitude) for latitude, longitude in rows]


def start_run(connection: Connection, task: str) -> int:
    run_id: int = connection.execute(
        ingestion_runs.insert()
        .values(task=task, started_at=func.now(), status="running")
        .returning(ingestion_runs.c.id)
    ).scalar_one()
    return run_id


def finish_run(
    connection: Connection, run_id: int, status: str, rows: int, error: str | None = None
) -> None:
    connection.execute(
        ingestion_runs.update()
        .where(ingestion_runs.c.id == run_id)
        .values(finished_at=func.now(), status=status, rows_upserted=rows, error=error)
    )


def latest_lowcost_times(connection: Connection) -> dict[int, datetime]:
    """Newest stored hour of every paired low-cost sensor that has readings, by database id."""
    rows = connection.execute(
        select(lowcost_readings.c.sensor_id, func.max(lowcost_readings.c.time))
        .where(lowcost_readings.c.sensor_id.in_(select(sensor_pairs.c.lowcost_sensor_id)))
        .group_by(lowcost_readings.c.sensor_id)
    )
    return {sensor_id: latest for sensor_id, latest in rows}
