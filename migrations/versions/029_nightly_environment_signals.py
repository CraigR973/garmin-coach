"""Persist nightly setup and missing weather signals (Batch 219).

Revision ID: 029
Revises: 028
Create Date: 2026-08-24

The manual setup belongs to the wake-morning ``manual_entries.entry_date``: it
records the bedding, windows, blind and pre-cool settings used for the night
that just ended. Weather remains one row per wake date; the new fields are
honest reductions of Open-Meteo's hourly overnight samples.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "029"
down_revision: str | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "manual_entries",
        sa.Column(
            "sleep_setup_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="coach",
    )
    op.add_column(
        "weather_daily",
        sa.Column("overnight_wind_direction_deg", sa.Float(), nullable=True),
        schema="coach",
    )
    op.add_column(
        "weather_daily",
        sa.Column("overnight_relative_humidity_mean_pct", sa.Float(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column(
        "weather_daily",
        "overnight_relative_humidity_mean_pct",
        schema="coach",
    )
    op.drop_column("weather_daily", "overnight_wind_direction_deg", schema="coach")
    op.drop_column("manual_entries", "sleep_setup_json", schema="coach")
