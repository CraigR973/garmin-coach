"""Add garmin_workout_deliveries for outdoor structured-workout delivery.

Revision ID: 014
Revises: 013
Create Date: 2026-07-10

Batch 78: an outdoor ride is uploaded + scheduled directly on Garmin Connect via
the existing garth session (Decision #151). This table records the outbound
delivery per calendar slot — the Garmin workout-template id + scheduled-workout
id used to re-sync/replace in place, the uploaded payload, the IR snapshot, and
an honest ``last_error`` on failure. Deliberately separate from
``workout_delivery_proposals`` (the intervals.icu/Zwift rail) so the Garmin write
path is fully isolated. Unique on ``(user_id, workout_date)`` — one live Garmin
delivery per slot, robust to Batch 77 row re-versioning.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "garmin_workout_deliveries",
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
        sa.Column(
            "planned_workout_id",
            UUID(as_uuid=True),
            sa.ForeignKey("planned_workouts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("planned_workout_version", sa.Integer(), nullable=False),
        sa.Column("workout_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pushed"),
        sa.Column("garmin_workout_id", sa.String(120), nullable=True),
        sa.Column("garmin_schedule_id", sa.String(120), nullable=True),
        sa.Column(
            "garmin_payload",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "structured_workout_ir",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("pushed_at_utc", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint(
            "user_id",
            "workout_date",
            name="uq_garmin_workout_delivery_user_date",
        ),
        schema="coach",
    )
    op.create_index(
        "ix_garmin_workout_deliveries_user_status",
        "garmin_workout_deliveries",
        ["user_id", "status"],
        schema="coach",
    )
    op.create_index(
        "ix_garmin_workout_deliveries_planned_workout",
        "garmin_workout_deliveries",
        ["planned_workout_id"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_garmin_workout_deliveries_planned_workout",
        table_name="garmin_workout_deliveries",
        schema="coach",
    )
    op.drop_index(
        "ix_garmin_workout_deliveries_user_status",
        table_name="garmin_workout_deliveries",
        schema="coach",
    )
    op.drop_table("garmin_workout_deliveries", schema="coach")
