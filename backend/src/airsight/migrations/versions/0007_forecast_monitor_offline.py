"""Record whether each forecast was made without the nearby monitor's reading (ADR 0012).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Decided when the forecast is issued, not when it is read: AirNow often delivers the
    # monitor's reading hours later, and the forecast was still made without it
    op.execute("ALTER TABLE forecasts ADD COLUMN monitor_offline boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE forecasts DROP COLUMN monitor_offline")
