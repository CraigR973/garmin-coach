"""Add fan_state_readings time-series for the overnight bedroom chart.

Revision ID: 011
Revises: 010
Create Date: 2026-06-30

A genuine 15-min time series (like ``temperature_readings`` /
``activity_timeseries``), written by ``scheduler.run_fan_control`` so the
bedroom chart can show what the fan actually did each night. No change to the
fan decision logic — this only persists the loop's outcome.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "fan_state_readings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_at_utc", sa.DateTime(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("auto_enabled", sa.Boolean(), nullable=False),
        sa.Column("observed_temp_c", sa.Float(), nullable=True),
        sa.Column("fan_on", sa.Boolean(), nullable=True),
        sa.Column("fan_speed", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint(
            "user_id",
            "captured_at_utc",
            name="uq_fan_state_reading_user_time",
        ),
        schema="coach",
    )
    op.create_index(
        "ix_fan_state_readings_user_time",
        "fan_state_readings",
        ["user_id", "captured_at_utc"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_fan_state_readings_user_time",
        table_name="fan_state_readings",
        schema="coach",
    )
    op.drop_table("fan_state_readings", schema="coach")
