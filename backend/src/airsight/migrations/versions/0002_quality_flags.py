"""Add data quality: per-hour flags on low-cost readings and a sensor health table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Computed by PostgreSQL from the two counters on every insert and update, so no code
    # path can forget it, and existing rows get it immediately. Bits: 1 missing channel,
    # 2 impossible (over 1,000 µg/m³), 4 both counters stuck at zero, 8 counters disagree
    # (EPA rule: more than 5 µg/m³ AND more than 70% apart).
    op.execute("""
        ALTER TABLE lowcost_readings ADD COLUMN flags smallint NOT NULL GENERATED ALWAYS AS ((
              CASE WHEN pm25_a IS NULL OR pm25_b IS NULL THEN 1 ELSE 0 END
            | CASE WHEN pm25_a > 1000 OR pm25_b > 1000 THEN 2 ELSE 0 END
            | CASE WHEN pm25_a = 0 AND pm25_b = 0 THEN 4 ELSE 0 END
            | CASE WHEN abs(pm25_a - pm25_b) > 5
                    AND abs(pm25_a - pm25_b) > 0.7 * (pm25_a + pm25_b) / 2 THEN 8 ELSE 0 END
        )::smallint) STORED
    """)

    op.execute("""
        CREATE TABLE sensor_health (
            sensor_id        bigint PRIMARY KEY REFERENCES sensors (id),
            checked_at       timestamptz NOT NULL,
            window_start     timestamptz NOT NULL,
            hours            integer NOT NULL,
            impossible_share real NOT NULL,
            disagree_share   real NOT NULL,
            median_pm25      real,
            median_reference real,
            status           text NOT NULL,
            reason           text,
            CONSTRAINT sensor_health_status_check CHECK (status IN ('ok', 'excluded'))
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE sensor_health")
    op.execute("ALTER TABLE lowcost_readings DROP COLUMN flags")
