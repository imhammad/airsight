"""Add day-ahead weather: what was forecast 24 hours before each hour (ADR 0012).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The same columns as observed weather, in a table of its own: the forecast model must train
    # on forecasts only, and a separate table makes mixing the two up impossible
    op.execute("""
        CREATE TABLE day_ahead_weather (
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
    op.execute("SELECT create_hypertable('day_ahead_weather', by_range('time'))")


def downgrade() -> None:
    op.execute("DROP TABLE day_ahead_weather")
