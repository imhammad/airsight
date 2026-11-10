"""Table definitions used by the application code.

Migrations in airsight/migrations create the real tables. These definitions must match them,
and tests/test_migrations.py fails if they drift apart.
"""

from geoalchemy2 import Geography
from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    FetchedValue,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    func,
)

metadata = MetaData()

sensors = Table(
    "sensors",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("source", Text, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("name", Text),
    Column("location", Geography("POINT", srid=4326), nullable=False),
    Column("weather_cell_id", Text),
    Column("active", Boolean, nullable=False, server_default="true"),
    UniqueConstraint("source", "source_id"),
    CheckConstraint("kind IN ('lowcost', 'reference')", name="sensors_kind_check"),
)

lowcost_readings = Table(
    "lowcost_readings",
    metadata,
    Column("sensor_id", BigInteger, ForeignKey("sensors.id"), primary_key=True),
    Column("time", DateTime(timezone=True), primary_key=True),
    Column("pm25_a", REAL),
    Column("pm25_b", REAL),
    Column("humidity", REAL),
    Column("temperature", REAL),
    # Computed by PostgreSQL (migration 0002); the app never writes it. Bits in quality.Flag.
    Column("flags", SmallInteger, FetchedValue(), nullable=False),
)

reference_readings = Table(
    "reference_readings",
    metadata,
    Column("sensor_id", BigInteger, ForeignKey("sensors.id"), primary_key=True),
    Column("time", DateTime(timezone=True), primary_key=True),
    Column("pm25", REAL, nullable=False),
)

weather = Table(
    "weather",
    metadata,
    Column("cell_id", Text, primary_key=True),
    Column("time", DateTime(timezone=True), primary_key=True),
    Column("temperature", REAL),
    Column("relative_humidity", REAL),
    Column("wind_speed", REAL),
    Column("wind_direction", REAL),
    Column("precipitation", REAL),
)

sensor_pairs = Table(
    "sensor_pairs",
    metadata,
    Column("reference_sensor_id", BigInteger, ForeignKey("sensors.id"), primary_key=True),
    Column("lowcost_sensor_id", BigInteger, ForeignKey("sensors.id"), primary_key=True),
    Column("distance_m", REAL, nullable=False),
)

ingestion_runs = Table(
    "ingestion_runs",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("task", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", Text, nullable=False),
    Column("rows_upserted", Integer),
    Column("error", Text),
    CheckConstraint(
        "status IN ('running', 'succeeded', 'failed')", name="ingestion_runs_status_check"
    ),
)

sensor_health = Table(
    "sensor_health",
    metadata,
    Column("sensor_id", BigInteger, ForeignKey("sensors.id"), primary_key=True),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("window_start", DateTime(timezone=True), nullable=False),
    Column("hours", Integer, nullable=False),
    Column("impossible_share", REAL, nullable=False),
    Column("disagree_share", REAL, nullable=False),
    Column("median_pm25", REAL),
    Column("median_reference", REAL),
    Column("status", Text, nullable=False),
    Column("reason", Text),
    CheckConstraint("status IN ('ok', 'excluded')", name="sensor_health_status_check"),
)

corrected_readings = Table(
    "corrected_readings",
    metadata,
    Column("sensor_id", BigInteger, ForeignKey("sensors.id"), primary_key=True),
    Column("time", DateTime(timezone=True), primary_key=True),
    Column("pm25", REAL, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

serving_sources = Table(
    "serving_sources",
    metadata,
    Column("sensor_id", BigInteger, ForeignKey("sensors.id"), primary_key=True),
    Column("station_id", BigInteger, ForeignKey("sensors.id"), nullable=False),
    Column("source", Text, nullable=False),
    Column("hours", Integer, nullable=False),
    Column("corrected_mae", REAL),
    Column("raw_mae", REAL),
    Column("model_version", Text, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("source IN ('corrected', 'raw')", name="serving_sources_source_check"),
)
