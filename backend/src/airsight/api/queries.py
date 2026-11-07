"""Database reads behind the sensor and reading endpoints.

Only low-cost sensors paired with an official monitor are served: those are the ones we ingest
and correct. Public ids are built from the source (pa-131075), never from database ids.
"""

import base64
import binascii
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, RowMapping, text

from airsight.api.aqi import aqi_category, round_pm25
from airsight.api.schemas import NearbyReading, Reading, Sensor, SensorDetail

STALE_AFTER = timedelta(hours=6)  # two missed ingestions
PREFIXES = {"purpleair": "pa"}
SOURCES = {prefix: source for source, prefix in PREFIXES.items()}

SENSOR_COLUMNS = """
    s.source,
    s.source_id,
    s.name,
    ST_Y(s.location::geometry) AS latitude,
    ST_X(s.location::geometry) AS longitude,
    COALESCE(h.status, 'ok') AS health
"""

SERVED = """
    s.kind = 'lowcost'
    AND s.active
    AND EXISTS (SELECT 1 FROM sensor_pairs p WHERE p.lowcost_sensor_id = s.id)
"""

# The newest corrected value of each sensor, with the raw reading of the same hour
LATEST = """
    SELECT c.time, c.pm25, c.model_version, (l.pm25_a + l.pm25_b) / 2 AS raw
    FROM corrected_readings c
    LEFT JOIN lowcost_readings l ON l.sensor_id = c.sensor_id AND l.time = c.time
    WHERE c.sensor_id = s.id
    ORDER BY c.time DESC
    LIMIT 1
"""

LIST_SQL = text(f"""
    SELECT {SENSOR_COLUMNS}
    FROM sensors s
    LEFT JOIN sensor_health h ON h.sensor_id = s.id
    WHERE {SERVED} AND (s.source, s.source_id) > (:after_source, :after_source_id)
    ORDER BY s.source, s.source_id
    LIMIT :limit
""")

DETAIL_SQL = text(f"""
    SELECT {SENSOR_COLUMNS}, latest.*
    FROM sensors s
    LEFT JOIN sensor_health h ON h.sensor_id = s.id
    LEFT JOIN LATERAL ({LATEST}) latest ON COALESCE(h.status, 'ok') <> 'excluded'
    WHERE {SERVED} AND s.source = :source AND s.source_id = :source_id
""")

NEAREST_SQL = text(f"""
    WITH here AS (SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography AS point)
    SELECT {SENSOR_COLUMNS}, ST_Distance(s.location, here.point) AS distance_m, latest.*
    FROM sensors s
    CROSS JOIN here
    LEFT JOIN sensor_health h ON h.sensor_id = s.id
    JOIN LATERAL ({LATEST}) latest ON true
    WHERE {SERVED}
      AND COALESCE(h.status, 'ok') <> 'excluded'
      AND ST_DWithin(s.location, here.point, :radius_m)
    ORDER BY distance_m
    LIMIT :limit
""")


class InvalidCursorError(ValueError):
    pass


def public_id(source: str, source_id: str) -> str:
    return f"{PREFIXES[source]}-{source_id}"


def parse_public_id(sensor_id: str) -> tuple[str, str] | None:
    """(source, source_id) for an id such as pa-131075, or None if it can't be one of ours."""
    prefix, _, source_id = sensor_id.partition("-")
    if prefix not in SOURCES or not source_id.isdigit():
        return None
    return SOURCES[prefix], source_id


def encode_cursor(sensor: Sensor) -> str:
    return base64.urlsafe_b64encode(sensor.id.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError) as error:
        raise InvalidCursorError(cursor) from error
    parsed = parse_public_id(decoded)
    if parsed is None:
        raise InvalidCursorError(cursor)
    return parsed


def _sensor(row: RowMapping) -> Sensor:
    return Sensor(
        id=public_id(row["source"], row["source_id"]),
        name=row["name"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        health=row["health"],
    )


def _reading(row: RowMapping, now: datetime) -> Reading | None:
    if row["time"] is None:
        return None
    observed_at = row["time"].astimezone(UTC)
    return Reading(
        pm25_corrected=round_pm25(row["pm25"]),
        pm25_raw=None if row["raw"] is None else round_pm25(row["raw"]),
        aqi_category=aqi_category(row["pm25"]),
        model_version=row["model_version"],
        observed_at=observed_at,
        stale=now - observed_at > STALE_AFTER,
    )


def list_sensors(
    connection: Connection, cursor: str | None, limit: int
) -> tuple[list[Sensor], str | None]:
    """One page of served sensors in a stable order, and the cursor of the next page."""
    after_source, after_source_id = decode_cursor(cursor) if cursor else ("", "")
    rows = connection.execute(
        LIST_SQL,
        {"after_source": after_source, "after_source_id": after_source_id, "limit": limit + 1},
    ).mappings()
    page = [_sensor(row) for row in rows]
    if len(page) <= limit:
        return page, None
    page = page[:limit]
    return page, encode_cursor(page[-1])


def get_sensor(connection: Connection, sensor_id: str, now: datetime) -> SensorDetail | None:
    parsed = parse_public_id(sensor_id)
    if parsed is None:
        return None
    source, source_id = parsed
    row = (
        connection.execute(DETAIL_SQL, {"source": source, "source_id": source_id})
        .mappings()
        .first()
    )
    if row is None:
        return None
    return SensorDetail(**_sensor(row).model_dump(), latest_reading=_reading(row, now))


def nearest(
    connection: Connection,
    latitude: float,
    longitude: float,
    radius_km: float,
    limit: int,
    now: datetime,
) -> list[NearbyReading]:
    """Latest readings of the closest healthy sensors within radius_km, nearest first."""
    rows = connection.execute(
        NEAREST_SQL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "radius_m": radius_km * 1000,
            "limit": limit,
        },
    ).mappings()
    nearby = []
    for row in rows:
        reading = _reading(row, now)
        assert reading is not None  # the inner lateral join guarantees a reading
        nearby.append(
            NearbyReading(
                sensor=_sensor(row), distance_km=round(row["distance_m"] / 1000, 2), reading=reading
            )
        )
    return nearby


HISTORY_SQL = text(f"""
    SELECT c.time, c.pm25, c.model_version, (l.pm25_a + l.pm25_b) / 2 AS raw
    FROM sensors s
    LEFT JOIN sensor_health h ON h.sensor_id = s.id
    JOIN corrected_readings c ON c.sensor_id = s.id
    LEFT JOIN lowcost_readings l ON l.sensor_id = c.sensor_id AND l.time = c.time
    WHERE {SERVED}
      AND COALESCE(h.status, 'ok') <> 'excluded'
      AND s.source = :source AND s.source_id = :source_id
      AND c.time >= :start AND c.time < :end
    ORDER BY c.time
""")


def history(
    connection: Connection, sensor_id: str, start: datetime, end: datetime, now: datetime
) -> list[Reading]:
    """Hourly corrected readings in [start, end), oldest first. Empty for excluded sensors."""
    parsed = parse_public_id(sensor_id)
    if parsed is None:
        return []
    source, source_id = parsed
    rows = connection.execute(
        HISTORY_SQL, {"source": source, "source_id": source_id, "start": start, "end": end}
    ).mappings()
    return [reading for row in rows if (reading := _reading(row, now)) is not None]
