"""Add forecasts: every hour of every issued air quality forecast (ADR 0012).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every issue is kept, not only the latest, so the live forecast can be scored later the
    # same way as the live correction. Issuing the same hour again replaces it.
    op.execute("""
        CREATE TABLE forecasts (
            sensor_id          bigint NOT NULL REFERENCES sensors (id),
            issue_time         timestamptz NOT NULL,
            horizon            smallint NOT NULL CHECK (horizon BETWEEN 1 AND 24),
            target_time        timestamptz NOT NULL,
            p10                real NOT NULL,
            p50                real NOT NULL,
            p90                real NOT NULL,
            outside_experience boolean NOT NULL,
            model_version      text NOT NULL,
            computed_at        timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (sensor_id, issue_time, horizon),
            CHECK (0 <= p10 AND p10 <= p50 AND p50 <= p90)
        )
    """)
    op.execute("SELECT create_hypertable('forecasts', by_range('issue_time'))")


def downgrade() -> None:
    op.execute("DROP TABLE forecasts")
