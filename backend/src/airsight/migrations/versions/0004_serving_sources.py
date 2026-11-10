"""Add serving sources: whether each sensor shows its corrected or its raw reading (ADR 0010).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per served sensor, rewritten after every correction run. The scores that led to
    # the choice are kept next to it, so any switch to raw can be explained later.
    op.execute("""
        CREATE TABLE serving_sources (
            sensor_id     bigint PRIMARY KEY REFERENCES sensors (id),
            station_id    bigint NOT NULL REFERENCES sensors (id),
            source        text NOT NULL,
            hours         integer NOT NULL,
            corrected_mae real,
            raw_mae       real,
            model_version text NOT NULL,
            decided_at    timestamptz NOT NULL,
            CONSTRAINT serving_sources_source_check CHECK (source IN ('corrected', 'raw'))
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE serving_sources")
