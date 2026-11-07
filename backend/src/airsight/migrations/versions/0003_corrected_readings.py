"""Add corrected readings: the champion model's PM2.5 for each clean sensor-hour.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One corrected value per sensor-hour. Recomputing an hour (with a newer model, or once late
    # weather arrives) replaces it, and model_version always says which model produced it.
    op.execute("""
        CREATE TABLE corrected_readings (
            sensor_id     bigint NOT NULL REFERENCES sensors (id),
            time          timestamptz NOT NULL,
            pm25          real NOT NULL,
            model_version text NOT NULL,
            computed_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (sensor_id, time)
        )
    """)
    op.execute("SELECT create_hypertable('corrected_readings', by_range('time'))")


def downgrade() -> None:
    op.execute("DROP TABLE corrected_readings")
