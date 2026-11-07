from datetime import UTC, datetime

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert

from airsight.core.tables import lowcost_readings, metadata, sensors


def add_sensor(engine: Engine, source_id: str) -> int:
    with engine.begin() as connection:
        sensor_id: int = connection.execute(
            sensors.insert()
            .values(
                source="purpleair",
                source_id=source_id,
                kind="lowcost",
                location="SRID=4326;POINT(-122.42 37.77)",
            )
            .returning(sensors.c.id)
        ).scalar_one()
    return sensor_id


def test_tables_match_definitions(engine: Engine) -> None:
    inspector = inspect(engine)

    for table in metadata.sorted_tables:
        in_database = {c["name"]: c["nullable"] for c in inspector.get_columns(table.name)}
        in_code = {c.name: c.nullable for c in table.columns}
        assert in_database == in_code, f"{table.name} differs from airsight.core.tables"


def test_time_series_tables_are_hypertables(engine: Engine) -> None:
    with engine.connect() as connection:
        names = connection.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        ).scalars()

        assert set(names) == {
            "lowcost_readings",
            "reference_readings",
            "weather",
            "corrected_readings",
        }


def test_writing_the_same_reading_twice_keeps_one_row(engine: Engine) -> None:
    sensor_id = add_sensor(engine, "idempotency-test")
    time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    for pm25 in (10.0, 12.5):
        statement = insert(lowcost_readings).values(sensor_id=sensor_id, time=time, pm25_a=pm25)
        statement = statement.on_conflict_do_update(
            index_elements=["sensor_id", "time"],
            set_={"pm25_a": statement.excluded.pm25_a},
        )
        with engine.begin() as connection:
            connection.execute(statement)

    with engine.connect() as connection:
        rows = connection.execute(
            select(lowcost_readings.c.pm25_a).where(lowcost_readings.c.sensor_id == sensor_id)
        ).scalars()

        assert list(rows) == [12.5]


def test_hourly_aggregate_averages_readings(engine: Engine) -> None:
    sensor_id = add_sensor(engine, "hourly-test")
    with engine.begin() as connection:
        connection.execute(
            lowcost_readings.insert(),
            [
                {
                    "sensor_id": sensor_id,
                    "time": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                    "pm25_a": 10.0,
                },
                {
                    "sensor_id": sensor_id,
                    "time": datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
                    "pm25_a": 20.0,
                },
            ],
        )

    # Refreshing a continuous aggregate can't run inside a transaction
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("CALL refresh_continuous_aggregate('lowcost_hourly', NULL, NULL)"))
        row = connection.execute(
            text("SELECT pm25_a, n_readings FROM lowcost_hourly WHERE sensor_id = :id"),
            {"id": sensor_id},
        ).one()

    assert row.pm25_a == 15.0
    assert row.n_readings == 2
