"""Create the ingestion schema: sensors, readings, weather, pairs and run history.

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.execute("""
        CREATE TABLE sensors (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source          text NOT NULL,
            source_id       text NOT NULL,
            kind            text NOT NULL,
            name            text,
            location        geography(Point, 4326) NOT NULL,
            weather_cell_id text,
            active          boolean NOT NULL DEFAULT true,
            UNIQUE (source, source_id),
            CONSTRAINT sensors_kind_check CHECK (kind IN ('lowcost', 'reference'))
        )
    """)
    op.execute("CREATE INDEX sensors_location_idx ON sensors USING gist (location)")

    op.execute("""
        CREATE TABLE lowcost_readings (
            sensor_id   bigint NOT NULL REFERENCES sensors (id),
            time        timestamptz NOT NULL,
            pm25_a      real,
            pm25_b      real,
            humidity    real,
            temperature real,
            PRIMARY KEY (sensor_id, time)
        )
    """)
    op.execute("SELECT create_hypertable('lowcost_readings', by_range('time'))")

    op.execute("""
        CREATE TABLE reference_readings (
            sensor_id bigint NOT NULL REFERENCES sensors (id),
            time      timestamptz NOT NULL,
            pm25      real NOT NULL,
            PRIMARY KEY (sensor_id, time)
        )
    """)
    op.execute("SELECT create_hypertable('reference_readings', by_range('time'))")

    op.execute("""
        CREATE TABLE weather (
            cell_id           text NOT NULL,
            time              timestamptz NOT NULL,
            temperature       real,
            relative_humidity real,
            wind_speed        real,
            wind_direction    real,
            precipitation     real,
            PRIMARY KEY (cell_id, time)
        )
    """)
    op.execute("SELECT create_hypertable('weather', by_range('time'))")

    op.execute("""
        CREATE TABLE sensor_pairs (
            reference_sensor_id bigint NOT NULL REFERENCES sensors (id),
            lowcost_sensor_id   bigint NOT NULL REFERENCES sensors (id),
            distance_m          real NOT NULL,
            PRIMARY KEY (reference_sensor_id, lowcost_sensor_id)
        )
    """)

    op.execute("""
        CREATE TABLE ingestion_runs (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            task          text NOT NULL,
            started_at    timestamptz NOT NULL,
            finished_at   timestamptz,
            status        text NOT NULL,
            rows_upserted integer,
            error         text,
            CONSTRAINT ingestion_runs_status_check
                CHECK (status IN ('running', 'succeeded', 'failed'))
        )
    """)

    # Hourly averages, kept up to date by TimescaleDB. WITH NO DATA lets this run inside
    # the migration's transaction. The backfill job refreshes older history explicitly.
    op.execute("""
        CREATE MATERIALIZED VIEW lowcost_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            sensor_id,
            time_bucket(INTERVAL '1 hour', time) AS hour,
            avg(pm25_a)      AS pm25_a,
            avg(pm25_b)      AS pm25_b,
            avg(humidity)    AS humidity,
            avg(temperature) AS temperature,
            count(*)         AS n_readings
        FROM lowcost_readings
        GROUP BY sensor_id, hour
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy(
            'lowcost_hourly',
            start_offset      => INTERVAL '3 days',
            end_offset        => INTERVAL '1 hour',
            schedule_interval => INTERVAL '30 minutes'
        )
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW lowcost_hourly")
    op.execute("DROP TABLE ingestion_runs")
    op.execute("DROP TABLE sensor_pairs")
    op.execute("DROP TABLE weather")
    op.execute("DROP TABLE reference_readings")
    op.execute("DROP TABLE lowcost_readings")
    op.execute("DROP TABLE sensors")
