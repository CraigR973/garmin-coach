"""Add overnight wind columns to weather daily.

Revision ID: 003
Revises: 002
Create Date: 2026-06-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weather_daily",
        sa.Column("overnight_wind_max_mph", sa.Float(), nullable=True),
        schema="coach",
    )
    op.add_column(
        "weather_daily",
        sa.Column("overnight_wind_gust_mph", sa.Float(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.drop_column("weather_daily", "overnight_wind_gust_mph", schema="coach")
    op.drop_column("weather_daily", "overnight_wind_max_mph", schema="coach")
