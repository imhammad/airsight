"""Daily drift score of each model input (ADR 0013).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per input per daily check. The exporter reads the newest check; older ones stay
    # so drift can be followed over time.
    op.execute("""
        CREATE TABLE input_drift (
            checked_at        timestamptz NOT NULL,
            feature           text NOT NULL,
            model_version     text NOT NULL,
            score             real,
            drifted           boolean NOT NULL,
            reference_median  real,
            current_median    real,
            PRIMARY KEY (checked_at, feature)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE input_drift")
