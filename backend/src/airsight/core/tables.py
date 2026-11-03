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
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
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
